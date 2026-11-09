"""HTTP transport validates the numeric address handed to the socket connector.

The URL hostname is unchanged, preserving Host, TLS SNI and certificate checks.
Redirects pass through this same boundary. Ambient/request proxies are disabled.
"""

import asyncio
import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import aiohttp
from aiohttp.abc import AbstractResolver
from yarl import URL

from .scope import current_scope


class UnsafeDestination(ValueError):
    pass


def approve_address(value):
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        approve_address(str(address.ipv4_mapped))
    tunnels = ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32")
    if (
        not address.is_global
        or address.is_multicast
        or address.is_reserved
        or any(address in ipaddress.ip_network(prefix) for prefix in tunnels)
    ):
        raise UnsafeDestination("Non-public network destination rejected")
    return str(address)


def approve_url(value):
    url = URL(value)
    if url.scheme not in {"http", "https"} or not url.host or url.user is not None:
        raise UnsafeDestination("Only HTTP(S) URLs without credentials are permitted")
    host = url.host.lower().rstrip(".")
    if (
        "%" in host
        or host == "localhost"
        or host.endswith(".localhost")
        or host
        in {"metadata.google.internal", "metadata.goog", "instance-data.ec2.internal"}
    ):
        raise UnsafeDestination("Local/metadata hostname rejected")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        approve_address(host)
    return url


class PublicResolver(AbstractResolver):
    def __init__(self):
        self.executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="crawler-dns"
        )
        self.pending = set()
        self.closed = False

    async def resolve(self, host, port=0, family=socket.AF_UNSPEC):
        if self.closed:
            raise RuntimeError("Resolver is closed")
        future = self.executor.submit(
            socket.getaddrinfo, host, port, family=family, type=socket.SOCK_STREAM
        )
        self.pending.add(future)
        # Cancellation may stop the await, never erase the underlying DNS work.
        try:
            answers = await asyncio.shield(asyncio.wrap_future(future))
        finally:
            if future.done():
                self.pending.discard(future)
        result = []
        for address_family, _, proto, _, sockaddr in answers:
            ip = approve_address(sockaddr[0])
            result.append(
                dict(
                    hostname=host,
                    host=ip,
                    port=port,
                    family=address_family,
                    proto=proto,
                    flags=socket.AI_NUMERICHOST,
                )
            )
        if not result:
            raise UnsafeDestination("DNS returned no public addresses")
        return result

    async def close(self):
        try:
            if self.pending:
                await asyncio.gather(
                    *(asyncio.wrap_future(f) for f in self.pending),
                    return_exceptions=True,
                )
        finally:
            # Joining is required even if cancellation interrupted the awaits.
            self.executor.shutdown(wait=True, cancel_futures=True)
            self.closed = True


def public_socket(addr_info):
    scope = current_scope.get()
    if scope and (scope.closed or scope.stopping):
        raise RuntimeError("Job network admission is closed")
    family, kind, proto, _, sockaddr = addr_info
    # Also covers IP literals, which aiohttp intentionally sends past its resolver.
    approve_address(sockaddr[0])
    return socket.socket(family=family, type=kind, proto=proto)


class SafeSession:
    def __init__(self, *, headers=None, timeout=None, limit=20):
        self.scope = current_scope.get()
        if self.scope and (self.scope.closed or self.scope.stopping):
            raise RuntimeError("Job network admission is closed")
        self.resolver = PublicResolver()
        connector = aiohttp.TCPConnector(
            resolver=self.resolver,
            socket_factory=public_socket,
            use_dns_cache=False,
            force_close=True,
            limit=limit,
            limit_per_host=limit,
        )
        self.session = aiohttp.ClientSession(
            headers=headers,
            connector=connector,
            trust_env=False,
            timeout=timeout or aiohttp.ClientTimeout(total=120),
        )
        if self.scope:
            self.scope.sessions.add(self)

    @property
    def closed(self):
        return self.session.closed and self.resolver.closed

    async def close(self):
        try:
            await self.session.close()
        finally:
            await self.resolver.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def head(self, url, **kwargs):
        return self.request("HEAD", url, **kwargs)

    @asynccontextmanager
    async def request(self, method, url, **kwargs):
        if self.scope and (self.scope.closed or self.scope.stopping):
            raise RuntimeError("Job network admission is closed")
        url = approve_url(url)
        redirects = kwargs.pop("allow_redirects", True)
        maximum = min(kwargs.pop("max_redirects", 10), 10)
        if any(
            key in kwargs
            for key in (
                "proxy",
                "proxy_auth",
                "ssl",
                "verify_ssl",
                "ssl_context",
                "server_hostname",
            )
        ):
            raise UnsafeDestination("Transport security overrides are forbidden")
        for hop in range(maximum + 1):
            async with self.session.request(
                method, url, allow_redirects=False, **kwargs
            ) as response:
                if (
                    redirects
                    and response.status in {301, 302, 303, 307, 308}
                    and response.headers.get("Location")
                ):
                    if hop == maximum:
                        raise UnsafeDestination("Redirect limit exceeded")
                    target = approve_url(url.join(URL(response.headers["Location"])))
                    if target.origin() != url.origin() and "headers" in kwargs:
                        kwargs["headers"] = {
                            k: v
                            for k, v in kwargs["headers"].items()
                            if k.lower() not in {"authorization", "cookie", "host"}
                        }
                    url = target
                    continue
                yield response
                return

"""Private browser proxy; all upstream sockets use the existing numeric policy.

HTTPS stays an opaque CONNECT tunnel. HTTP redirects are returned to Chromium;
the next hop must enter this broker again. No target socket is opened by the
browser namespace itself.
"""

import asyncio
import socket
from collections import deque
from contextlib import suppress

import aiohttp
from yarl import URL

from .network import (
    PublicResolver,
    SafeSession,
    UnsafeDestination,
    approve_url,
    public_socket,
)

HEADER_LIMIT = 65536
BODY_LIMIT = 16 * 1024 * 1024


async def close_writer(writer):
    writer.close()
    with suppress(ConnectionError, OSError):
        await writer.wait_closed()


async def relay(left_reader, left_writer, right_reader, right_writer):
    async def pump(reader, writer):
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()

    tasks = [
        asyncio.create_task(pump(left_reader, right_writer)),
        asyncio.create_task(pump(right_reader, left_writer)),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await close_writer(left_writer)
        await close_writer(right_writer)


class EgressBroker:
    def __init__(self):
        self.resolver = PublicResolver()
        self.server = None
        self.http = None
        self.handlers = set()
        self.writers = set()
        self.closed = False
        self.closing = False
        self.connections = deque(maxlen=1024)
        self.rejections = deque(maxlen=1024)

    async def start(self, path):
        self.server = await asyncio.start_unix_server(
            self.handle, path, limit=HEADER_LIMIT
        )
        self.http = SafeSession()

    async def connect(self, url):
        url = approve_url(url)
        port = url.port or (443 if url.scheme == "https" else 80)
        answers = await self.resolver.resolve(url.host, port)
        last_error = None
        for answer in answers:
            address = (answer["host"], port)
            sock = public_socket(
                (answer["family"], socket.SOCK_STREAM, answer["proto"], "", address)
            )
            try:
                sock.setblocking(False)
                await asyncio.wait_for(
                    asyncio.get_running_loop().sock_connect(sock, address), 20
                )
                reader, writer = await asyncio.open_connection(sock=sock)
                self.writers.add(writer)
                self.connections.append((url.host, answer["host"], port))
                return reader, writer
            except BaseException as exc:
                sock.close()
                if not isinstance(exc, (OSError, asyncio.TimeoutError)):
                    raise
                last_error = exc
        raise OSError("No approved upstream address connected") from last_error

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.handlers.add(task)
        self.writers.add(writer)
        response_started = False
        upstream_writer = None
        try:
            if self.closed or self.closing:
                return
            raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 15)
            lines = raw.decode("latin-1").split("\r\n")
            method, target, version = lines[0].split(" ")
            if version not in {"HTTP/1.0", "HTTP/1.1"}:
                raise ValueError("Unsupported proxy request")
            headers = {}
            for line in lines[1:]:
                if not line:
                    continue
                name, value = line.split(":", 1)
                name = name.lower()
                if name in headers or not name or name.strip() != name:
                    raise ValueError("Ambiguous proxy headers")
                headers[name] = value.strip()
            if method == "CONNECT":
                url = approve_url("https://" + target)
                if (
                    url.raw_authority != target
                    or url.path != "/"
                    or url.query_string
                    or url.fragment
                ):
                    raise ValueError("Invalid CONNECT authority")
                upstream_reader, upstream_writer = await self.connect(url)
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()
                response_started = True
                await relay(reader, writer, upstream_reader, upstream_writer)
            else:
                if method not in {
                    "GET",
                    "HEAD",
                    "POST",
                    "PUT",
                    "PATCH",
                    "DELETE",
                    "OPTIONS",
                }:
                    raise ValueError("Unsupported method")
                url = URL(target)
                if url.scheme == "ws":
                    url = url.with_scheme("http")
                url = approve_url(url)
                if url.scheme != "http":
                    raise ValueError("HTTPS requires CONNECT")
                if "transfer-encoding" in headers:
                    raise ValueError("Streaming request bodies are unsupported")
                length = int(headers.get("content-length", "0"))
                if not 0 <= length <= BODY_LIMIT:
                    raise ValueError("Request body too large")
                connection_headers = {
                    name.strip().lower()
                    for name in headers.get("connection", "").split(",")
                }
                outgoing = {
                    key: value
                    for key, value in headers.items()
                    if key
                    not in connection_headers
                    | {
                        "host",
                        "connection",
                        "proxy-connection",
                        "proxy-authorization",
                        "content-length",
                    }
                }
                outgoing["Host"] = url.raw_authority
                if headers.get("upgrade", "").lower() == "websocket":
                    if method != "GET" or length:
                        raise ValueError("Invalid WebSocket handshake")
                    outgoing["Connection"] = "Upgrade"
                    outgoing["Upgrade"] = "websocket"
                    upstream_reader, upstream_writer = await self.connect(url)
                    request = (
                        f"GET {url.raw_path_qs} HTTP/1.1\r\n"
                        + "".join(
                            f"{key}: {value}\r\n" for key, value in outgoing.items()
                        )
                        + "\r\n"
                    )
                    upstream_writer.write(request.encode("latin-1"))
                    await upstream_writer.drain()
                    response_started = True
                    await relay(reader, writer, upstream_reader, upstream_writer)
                else:
                    body = (
                        await asyncio.wait_for(reader.readexactly(length), 30)
                        if length
                        else None
                    )
                    async with self.http.request(
                        method,
                        url,
                        headers=outgoing,
                        data=body,
                        allow_redirects=False,
                    ) as response:
                        excluded = {
                            "connection",
                            "transfer-encoding",
                            "content-encoding",
                            "content-length",
                            "keep-alive",
                            "proxy-authenticate",
                        }
                        writer.write(
                            f"HTTP/1.1 {response.status} {response.reason}\r\n".encode(
                                "latin-1"
                            )
                        )
                        for key, value in response.headers.items():
                            if key.lower() not in excluded:
                                writer.write(f"{key}: {value}\r\n".encode("latin-1"))
                        writer.write(b"Connection: close\r\n\r\n")
                        response_started = True
                        async for data in response.content.iter_chunked(65536):
                            writer.write(data)
                            await writer.drain()
        except (UnsafeDestination, ValueError) as exc:
            self.rejections.append(str(exc))
            if not response_started:
                writer.write(
                    b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
                )
        except (
            TimeoutError,
            OSError,
            RuntimeError,
            aiohttp.ClientError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
        ):
            if not response_started:
                writer.write(
                    b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
                )
        finally:
            if upstream_writer:
                await close_writer(upstream_writer)
                self.writers.discard(upstream_writer)
            await close_writer(writer)
            self.writers.discard(writer)
            self.handlers.discard(task)

    async def close(self):
        if self.closed:
            return
        self.closing = True
        if self.server:
            self.server.close()
        for task in list(self.handlers):
            task.cancel()
        await asyncio.gather(*self.handlers, return_exceptions=True)
        for writer in self.writers:
            await close_writer(writer)
        self.writers.clear()
        if self.server:
            await self.server.wait_closed()
        if self.http:
            await self.http.close()
        await self.resolver.close()
        self.closed = True

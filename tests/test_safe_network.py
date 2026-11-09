"""Transport tests assert socket admission, not just URL preflight.

Positive local TCP tests explicitly replace only address policy in the test;
there is no production loopback exception/configuration switch.
"""

import socket
from contextlib import asynccontextmanager

import pytest
from aiohttp import web

from hawki_crawler.crawler.assets.asset_downloader import AssetDownloader
from hawki_crawler.crawler.assets.file_downloader import FileDownloader
from hawki_crawler.crawler.assets.image_downloader import ImageDownloader
from hawki_crawler.crawler.core.runtime.run_config import fallback_fetch_html
from hawki_crawler.crawler.sitemap.parser import SitemapParser
from hawki_crawler.runtime import network
from hawki_crawler.runtime.browser import BrowserTransportUnavailable, SafeBrowser


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://10.1.2.3/",
        "http://172.16.0.1/",
        "http://192.168.1.2/",
        "http://[fd00::1]/",
        "http://169.254.1.2/",
        "http://169.254.169.254/",
        "http://[fe80::1]/",
        "http://0.0.0.0/",
        "http://224.0.0.1/",
        "http://[::]/",
        "http://100.100.100.200/",
        "http://[::ffff:127.0.0.1]/",
        "http://[64:ff9b::a00:1]/",
        "file:///etc/passwd",
        "ftp://example.com/a",
        "http://metadata.google.internal/",
    ],
)
@pytest.mark.asyncio
async def test_rejected_destinations_never_reach_socket(monkeypatch, url):
    sockets = []

    def forbidden_socket(info):
        sockets.append(info)
        raise AssertionError("A rejected request reached socket creation")

    monkeypatch.setattr(network, "public_socket", forbidden_socket)
    async with network.SafeSession() as session:
        with pytest.raises(network.UnsafeDestination):
            async with session.get(url):
                pass
    assert sockets == []


@pytest.mark.asyncio
async def test_dns_private_answer_never_reaches_socket(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 80))
        ],
    )
    sockets = []
    monkeypatch.setattr(network, "public_socket", lambda info: sockets.append(info))
    async with network.SafeSession() as session:
        with pytest.raises((network.UnsafeDestination, OSError)):
            async with session.get("http://apparently-public.example/"):
                pass
    assert sockets == []


def test_socket_boundary_rechecks_actual_numeric_destination():
    with pytest.raises(network.UnsafeDestination):
        network.public_socket(
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        )
    sock = network.public_socket(
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
    )
    sock.close()


@asynccontextmanager
async def local_site(monkeypatch, handler, ssl_context=None):
    original_policy = network.approve_address
    original_socket = network.public_socket
    destinations = []

    # Test-only allowlist for an actual disposable TCP server.
    def test_policy(ip):
        return ip if ip == "127.0.0.1" else original_policy(ip)

    def observed_socket(info):
        result = original_socket(info)
        destinations.append(info[4][0])
        return result

    monkeypatch.setattr(network, "approve_address", test_policy)
    monkeypatch.setattr(network, "public_socket", observed_socket)
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=ssl_context)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        scheme = "https" if ssl_context else "http"
        yield f"{scheme}://127.0.0.1:{port}", destinations, port
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_allowed_redirect_connects_and_preserves_host(monkeypatch):
    hosts = []

    async def handler(request):
        hosts.append(request.host)
        if request.path == "/start":
            raise web.HTTPFound("/final")
        return web.Response(text="safe fixture")

    async with local_site(monkeypatch, handler) as (base, sockets, port):
        async with network.SafeSession() as session:
            async with session.get(base + "/start") as response:
                assert await response.text() == "safe fixture"
        assert sockets == ["127.0.0.1", "127.0.0.1"]
        assert hosts == [f"127.0.0.1:{port}"] * 2


@pytest.mark.parametrize(
    "target",
    [
        "http://10.0.0.1/",
        "http://169.254.169.254/",
        "http://localhost/",
        "http://[::1]/",
    ],
)
@pytest.mark.asyncio
async def test_redirect_never_opens_rejected_destination(monkeypatch, target):
    async def handler(request):
        raise web.HTTPFound(target)

    async with local_site(monkeypatch, handler) as (base, sockets, _):
        async with network.SafeSession() as session:
            with pytest.raises(network.UnsafeDestination):
                async with session.get(base):
                    pass
        assert sockets == ["127.0.0.1"]


@pytest.mark.asyncio
async def test_dns_rebinding_uses_no_second_resolution_at_connect_and_rejects_next_hop(
    monkeypatch,
):
    async def handler(request):
        raise web.HTTPFound("/next")

    async with local_site(monkeypatch, handler) as (_, sockets, port):
        lookups = []

        def resolve(host, supplied_port, **kwargs):
            lookups.append(host)
            ip = "127.0.0.1" if len(lookups) == 1 else "10.0.0.1"
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, supplied_port))]

        monkeypatch.setattr(socket, "getaddrinfo", resolve)
        async with network.SafeSession() as session:
            with pytest.raises((network.UnsafeDestination, OSError)):
                async with session.get(f"http://rebind.example:{port}/"):
                    pass
        assert lookups == ["rebind.example", "rebind.example"]
        assert sockets == ["127.0.0.1"]


def parser():
    return SitemapParser(
        headers={},
        sitemap_map={},
        sitemap_lastmod={},
        is_forbidden_url=lambda url: False,
        normalize_url_key=lambda u: u,
        normalize_sitemap_meta=lambda m: m,
        get_sitemap_date=lambda m: None,
    )


@pytest.mark.asyncio
async def test_sitemap_private_destination_rejected_before_socket(monkeypatch):
    sockets = []
    monkeypatch.setattr(network, "public_socket", lambda info: sockets.append(info))
    assert await parser().parse_sitemap("http://169.254.169.254/sitemap.xml") == []
    assert sockets == []


@pytest.mark.asyncio
async def test_nested_sitemap_and_safe_expansion(monkeypatch):
    async def handler(request):
        if request.path == "/safe.xml":
            return web.Response(
                text="<urlset><url><loc>https://example.com/page</loc></url></urlset>",
                content_type="application/xml",
            )
        return web.Response(
            text="<sitemapindex><sitemap><loc>http://10.0.0.1/sitemap.xml</loc></sitemap></sitemapindex>",
            content_type="application/xml",
        )

    async with local_site(monkeypatch, handler) as (base, sockets, _):
        assert await parser().parse_sitemap(base + "/safe.xml") == [
            "https://example.com/page"
        ]
        assert await parser().parse_sitemap(base + "/nested.xml") == []
        assert sockets == ["127.0.0.1"] * 2


class NoWait:
    async def acquire(self):
        pass


@pytest.mark.parametrize("surface", ["head", "image", "pdf", "file", "fallback"])
@pytest.mark.asyncio
async def test_secondary_surfaces_do_not_connect_to_private_destination(
    monkeypatch, tmp_path, surface
):
    sockets = []
    monkeypatch.setattr(network, "public_socket", lambda info: sockets.append(info))
    url = "http://169.254.169.254/secret.pdf"
    async with network.SafeSession() as session:
        if surface == "head":
            downloader = AssetDownloader(
                rate_limiter=NoWait(),
                headers={},
                http_session=session,
                asset_saver=None,
            )
            assert await downloader.fetch_head(url) == (None, {})
        elif surface == "image":
            assert (
                await ImageDownloader(rate_limiter=NoWait()).download_image(
                    url, session, tmp_path
                )
                is None
            )
        elif surface in {"pdf", "file"}:
            downloader = FileDownloader(
                rate_limiter=NoWait(), headers={}, asset_saver=None
            )
            method = (
                downloader.fetch_and_save_pdf
                if surface == "pdf"
                else downloader.fetch_and_save_file
            )
            assert await method(url, 1, session=session) is None
        else:
            with pytest.raises(network.UnsafeDestination):
                await fallback_fetch_html(url)
    assert sockets == []


def test_browser_subresources_are_fail_closed_before_browser_creation(monkeypatch):
    monkeypatch.setattr(
        "hawki_crawler.runtime.browser.linux_namespaces_available", lambda: False
    )
    with pytest.raises(BrowserTransportUnavailable, match="No browser was launched"):
        SafeBrowser()


@pytest.mark.asyncio
async def test_transport_rejects_tls_and_proxy_bypasses():
    async with network.SafeSession() as session:
        for override in (
            {"ssl": False},
            {"proxy": "http://127.0.0.1:9999"},
            {"server_hostname": "other"},
        ):
            with pytest.raises(network.UnsafeDestination):
                async with session.get("https://example.com/", **override):
                    pass
        assert session.session.trust_env is False
        assert session.session.connector._ssl is True


@pytest.mark.parametrize("via_sitemap", [False, True])
@pytest.mark.asyncio
async def test_real_file_crawl_produces_artifacts_without_browser(
    monkeypatch, tmp_path, via_sitemap
):
    from httpx import ASGITransport, AsyncClient

    from hawki_crawler.app import job_lifecycle
    from hawki_crawler.app.main import app

    async def handler(request):
        if request.path == "/sitemap.xml":
            return web.Response(
                text=f"<urlset><url><loc>http://{request.host}/sample.pdf</loc></url></urlset>",
                content_type="application/xml",
            )
        return web.Response(body=b"%PDF-1.4\n%%EOF", content_type="application/pdf")

    async with local_site(monkeypatch, handler) as (base, sockets, _):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/crawl",
                json={
                    "job_id": "http-file",
                    "url": base + ("/sitemap.xml" if via_sitemap else "/sample.pdf"),
                    "skip_images": True,
                    "max_pages": 1,
                    "max_rpm": 600000,
                },
            )
            assert response.status_code == 200
            await job_lifecycle.tasks["http-file"]
            receipt = (await client.get("/status/http-file")).json()
            assert receipt["status"] == "completed" and receipt["sealed"]
            files = (await client.get("/jobs/http-file/files")).json()["files"]
            assert any(file["name"].endswith(".pdf") for file in files)
            assert any(file["name"] == "completed_urls.json" for file in files)
            assert sockets == ["127.0.0.1"] * (3 if via_sitemap else 2)


@pytest.mark.asyncio
async def test_https_preserves_hostname_sni_host_and_certificate_verification(
    monkeypatch, tmp_path
):
    import datetime
    import ssl

    import aiohttp
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "public.example")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("public.example")]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_tls.load_cert_chain(cert_path, key_path)
    sni, hosts = [], []
    server_tls.set_servername_callback(lambda sock, name, context: sni.append(name))

    async def handler(request):
        hosts.append(request.host)
        return web.Response(text="verified TLS")

    async with local_site(monkeypatch, handler, server_tls) as (_, sockets, port):
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda host, port, **kw: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))
            ],
        )
        async with network.SafeSession() as session:
            # Test-only trusted CA; certificate and hostname verification stay on.
            session.session.connector._ssl = ssl.create_default_context(
                cafile=str(cert_path)
            )
            async with session.get(f"https://public.example:{port}/") as response:
                assert await response.text() == "verified TLS"
            with pytest.raises(aiohttp.ClientConnectorCertificateError):
                async with session.get(f"https://wrong.example:{port}/"):
                    pass
            assert session.session.connector._ssl.verify_mode == ssl.CERT_REQUIRED
        assert hosts == [f"public.example:{port}"]
        assert sni[0] == "public.example"

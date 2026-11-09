"""Real Chromium transport tests in a disposable Linux container.

The fixture's approved public address is assigned to container loopback by the
test launcher. Production destination policy is NEVER relaxed. Private sinks
are also reachable from the broker namespace, so an unsafe connection would be
observed. macOS/default-seccomp runs skip; the required container run fails
instead of skipping when its prerequisites are missing.
"""

import asyncio
import os
import socket
import ssl
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp import web
from crawl4ai.async_configs import BrowserConfig, CacheMode, CrawlerRunConfig
from httpx import ASGITransport, AsyncClient
from playwright.async_api import Error as PlaywrightError

from hawki_crawler.app import job_lifecycle
from hawki_crawler.app.main import app
from hawki_crawler.runtime import browser as browser_module
from hawki_crawler.runtime.browser import BrowserTransportUnavailable, SafeBrowser

PUBLIC_IP = "93.184.216.34"
PRIVATE_IP = "10.77.0.2"
METADATA_IP = "169.254.169.254"
WORDS = " ".join(
    [
        "This protected browser fixture contains useful rendered page content for extraction and verification."
    ]
    * 12
)


def required_or_skip(reason):
    if os.getenv("REQUIRE_PROTECTED_BROWSER_TESTS") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture
def browser_prerequisites():
    if sys.platform != "linux":
        required_or_skip("Protected Chromium requires Linux namespaces")
    probe = subprocess.run(
        [
            "/usr/bin/unshare",
            "--user",
            "--map-root-user",
            "--net",
            "--pid",
            "--fork",
            "--kill-child=KILL",
            "/bin/true",
        ],
        capture_output=True,
        check=False,
    )
    if probe.returncode:
        required_or_skip(
            "Container must permit user/network/PID namespaces: "
            + probe.stderr.decode()
        )
    with socket.socket() as sock:
        try:
            sock.bind((PUBLIC_IP, 0))
        except OSError:
            required_or_skip(
                "Disposable test container needs the public fixture IP alias"
            )


@dataclass
class Site:
    port: int
    hits: list = field(default_factory=list)
    lookups: dict = field(default_factory=dict)
    rebound: bool = False
    slow_started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)

    def url(self, path="/page", host="public.test", scheme="http"):
        return f"{scheme}://{host}:{self.port}{path}"

    @property
    def private_hits(self):
        return [
            path
            for host, path in self.hits
            if host.split(":")[0] in {"127.0.0.1", PRIVATE_IP, METADATA_IP, "localhost"}
        ]


@pytest_asyncio.fixture
async def website(browser_prerequisites, monkeypatch):
    site = Site(0)
    original_dns = socket.getaddrinfo

    def resolve(host, port, *args, **kwargs):
        if host in {"public.test", "other.test", "rebind.test", "wrong.test"}:
            site.lookups[host] = site.lookups.get(host, 0) + 1
            ip = PRIVATE_IP if host == "rebind.test" and site.rebound else PUBLIC_IP
            return original_dns(ip, port, *args, **kwargs)
        try:
            socket.inet_pton(socket.AF_INET, host)
        except (OSError, TypeError):
            raise socket.gaierror("Unconfigured test hostname") from None
        return original_dns(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)

    async def handler(request):
        site.hits.append((request.host, request.path))
        if request.path == "/redirect-safe":
            raise web.HTTPFound(site.url("/page", host="other.test"))
        if request.path == "/redirect-private":
            raise web.HTTPFound(
                site.url("/sink", host=request.query.get("host", PRIVATE_IP))
            )
        if request.path == "/rebind":
            site.rebound = True
            raise web.HTTPFound(site.url("/rebound", host="rebind.test"))
        if request.path == "/slow":
            site.slow_started.set()
            await site.release.wait()
            return web.Response(text=WORDS, content_type="text/html")
        if request.path == "/script.js":
            return web.Response(
                text='document.body.dataset.script="loaded";',
                content_type="application/javascript",
            )
        if request.path == "/style.css":
            return web.Response(
                text="body { --protected-style: loaded; }", content_type="text/css"
            )
        if request.path == "/image.svg":
            return web.Response(
                text='<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>',
                content_type="image/svg+xml",
            )
        if request.path == "/data":
            return web.Response(text="loaded")
        if request.path == "/ws":
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.send_str("protected-websocket")
            async for _ in ws:
                pass
            return ws
        html = f'<html><head><title>Protected fixture</title><link rel="stylesheet" href="/style.css"></head><body><main><p>{WORDS}</p><p id="rendered">initial</p></main><img src="/image.svg"><iframe src="/frame"></iframe><script src="/script.js"></script><script>document.getElementById("rendered").textContent="Rendered by isolated Chromium";fetch("/data").then(r=>r.text()).then(t=>document.body.dataset.fetch=t);</script></body></html>'
        if request.path == "/frame":
            html = "<html><body>safe frame</body></html>"
        return web.Response(text=html, content_type="text/html")

    application = web.Application()
    application.router.add_route("*", "/{path:.*}", handler)
    runner = web.AppRunner(application)
    await runner.setup()
    listener = web.TCPSite(runner, "0.0.0.0", 0)
    await listener.start()
    site.port = listener._server.sockets[0].getsockname()[1]
    try:
        yield site
    finally:
        site.release.set()
        await runner.cleanup()


def run_config():
    return CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        word_count_threshold=0,
        delay_before_return_html=0.1,
        page_timeout=10000,
    )


async def rejected_navigation(page, url):
    try:
        response = await page.goto(url)
    except PlaywrightError as exc:
        assert any(
            code in str(exc)
            for code in (
                "ERR_HTTP_RESPONSE_CODE_FAILURE",
                "ERR_TUNNEL_CONNECTION_FAILED",
            )
        ), str(exc)
    else:
        assert response.status in {403, 502}


@pytest.mark.asyncio
async def test_chromium_safe_page_renders_and_loads_subresources(website):
    async with SafeBrowser(
        config=BrowserConfig(headless=True, verbose=False)
    ) as browser:
        result = await browser.arun(website.url(), config=run_config())
        assert result.success, result.error_message
        assert "Rendered by isolated Chromium" in result.html
        assert (
            'data-script="loaded"' in result.html
            and 'data-fetch="loaded"' in result.html
        )
        assert browser.proof["pid"] == 1 and browser.proof["interfaces"] == ["lo"]
        assert browser.proof["netns"] != os.stat("/proc/self/ns/net").st_ino
        assert {"/style.css", "/script.js", "/image.svg", "/frame", "/data"}.issubset(
            {p for _, p in website.hits}
        )
    assert (
        browser.closed
        and browser.broker.closed
        and browser.process.returncode is not None
    )


@pytest.mark.parametrize(
    "host", ["localhost", "127.0.0.1", PRIVATE_IP, METADATA_IP, "[::1]", "[fd00::1]"]
)
@pytest.mark.asyncio
async def test_chromium_private_navigation_never_reaches_target(website, host):
    async with SafeBrowser() as browser:
        page = await browser.crawler.crawler_strategy.browser_manager.browser.new_page()
        await rejected_navigation(page, website.url("/sink", host=host))
        assert browser.broker.rejections
        assert not website.private_hits


@pytest.mark.parametrize("host", ["localhost", PRIVATE_IP, METADATA_IP])
@pytest.mark.asyncio
async def test_chromium_redirect_to_private_is_rejected(website, host):
    async with SafeBrowser() as browser:
        page = await browser.crawler.crawler_strategy.browser_manager.browser.new_page()
        await rejected_navigation(
            page, website.url("/redirect-private") + "?host=" + host
        )
        assert browser.broker.rejections
        assert not website.private_hits


@pytest.mark.asyncio
async def test_chromium_public_redirect_passes(website):
    async with SafeBrowser() as browser:
        result = await browser.arun(website.url("/redirect-safe"), config=run_config())
        assert result.success and "Rendered by isolated Chromium" in result.html


@pytest.mark.parametrize(
    "kind", ["image", "script", "css", "iframe", "fetch", "xhr", "websocket"]
)
@pytest.mark.asyncio
async def test_chromium_private_subresource_cannot_connect(website, kind):
    async with SafeBrowser() as browser:
        page = await browser.crawler.crawler_strategy.browser_manager.browser.new_page()
        await page.goto(website.url())
        private = website.url("/sink", host=PRIVATE_IP)
        await page.evaluate(
            """({kind, url}) => new Promise(resolve => {
          let el;
          if(kind==='fetch'){fetch(url).then(()=>resolve('done')).catch(()=>resolve('blocked'));return;}
          if(kind==='xhr'){el=new XMLHttpRequest();el.open('GET',url);el.onloadend=()=>resolve('done');el.send();return;}
          if(kind==='websocket'){el=new WebSocket(url.replace('http:','ws:'));el.onerror=()=>resolve('blocked');el.onopen=()=>resolve('open');return;}
          el=document.createElement(({image:'img',script:'script',css:'link',iframe:'iframe'})[kind]);
          el.onload=()=>resolve('done');el.onerror=()=>resolve('blocked');
          if(kind==='css'){el.rel='stylesheet';el.href=url;}else{el.src=url;}
          document.body.appendChild(el);setTimeout(()=>resolve('timeout'),1000);
        })""",
            {"kind": kind, "url": private},
        )
        assert not website.private_hits
        assert not any(path == "/sink" for _, path in website.hits)


@pytest.mark.asyncio
async def test_chromium_public_websocket_uses_bound_broker(website):
    async with SafeBrowser() as browser:
        page = await browser.crawler.crawler_strategy.browser_manager.browser.new_page()
        await page.goto(website.url())
        message = await page.evaluate(
            """url => new Promise((resolve,reject)=>{
          const socket=new WebSocket(url);socket.onmessage=e=>{resolve(e.data);socket.close();};socket.onerror=reject;
        })""",
            website.url("/ws", scheme="ws"),
        )
        assert message == "protected-websocket"
        assert any(ip == PUBLIC_IP for _, ip, _ in browser.broker.connections)


@pytest.mark.asyncio
async def test_chromium_dns_rebinding_does_not_reach_private_sink(website):
    async with SafeBrowser() as browser:
        page = await browser.crawler.crawler_strategy.browser_manager.browser.new_page()
        await rejected_navigation(page, website.url("/rebind", host="rebind.test"))
        assert website.lookups["rebind.test"] >= 2
        assert not any(path == "/rebound" for _, path in website.hits)
        assert not website.private_hits


@pytest.mark.asyncio
async def test_chromium_proxy_bypass_still_has_no_external_route(website):
    async with SafeBrowser() as browser:
        context = (
            await browser.crawler.crawler_strategy.browser_manager.browser.new_context(
                proxy={
                    "server": f"http://127.0.0.1:{browser.proof['proxy_port']}",
                    "bypass": "*",
                }
            )
        )
        page = await context.new_page()
        with pytest.raises(PlaywrightError):
            await page.goto(website.url("/bypass", host=PUBLIC_IP), timeout=5000)
        assert not any(path == "/bypass" for _, path in website.hits)
        await context.close()


@pytest.mark.asyncio
async def test_chromium_proxy_unavailable_never_falls_back(website):
    async with SafeBrowser() as browser:
        page = await browser.crawler.crawler_strategy.browser_manager.browser.new_page()
        await browser.broker.close()
        with pytest.raises(PlaywrightError):
            await page.goto(website.url("/unavailable"), timeout=5000)
        with pytest.raises(BrowserTransportUnavailable):
            await browser.arun(website.url())
        assert not any(path == "/unavailable" for _, path in website.hits)


@pytest.mark.asyncio
async def test_protected_chromium_job_produces_artifacts_and_seals(website):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/crawl",
            json={
                "job_id": "protected-browser",
                "url": website.url(),
                "skip_images": True,
                "max_pages": 1,
                "max_rpm": 60000,
            },
        )
        assert response.status_code == 200
        await asyncio.wait_for(job_lifecycle.tasks["protected-browser"], 30)
        receipt = (await client.get("/status/protected-browser")).json()
        assert receipt["status"] == "completed", receipt
        assert (
            receipt["terminal"]
            and receipt["sealed"]
            and receipt["quiescent"]
            and receipt["writer_admission_closed"]
        )
        root = Path(receipt["output_directory"])
        assert any(
            "Rendered by isolated Chromium" in p.read_text()
            for p in root.rglob("content.md")
        )
        assert (root / "completed_urls.json").is_file()


@pytest.mark.asyncio
async def test_cancellation_drains_real_chromium_and_proxy_before_seal(
    website, monkeypatch
):
    browsers = []
    original = browser_module.SafeBrowser.__aenter__

    async def observed(self):
        browsers.append(self)
        return await original(self)

    monkeypatch.setattr(browser_module.SafeBrowser, "__aenter__", observed)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.post(
            "/crawl",
            json={
                "job_id": "cancel-browser",
                "url": website.url("/slow"),
                "skip_images": True,
                "max_pages": 1,
            },
        )
        await asyncio.wait_for(website.slow_started.wait(), 20)
        await client.post("/jobs/cancel-browser/cancel")
        supervisor = job_lifecycle.tasks.get("cancel-browser")
        if supervisor:
            await asyncio.wait_for(asyncio.shield(supervisor), 20)
        receipt = (await client.get("/status/cancel-browser")).json()
        assert (
            receipt["status"] == "cancelled"
            and receipt["sealed"]
            and receipt["quiescent"]
        )
        assert all(
            b.closed and b.broker.closed and b.process.returncode is not None
            for b in browsers
        )


@pytest_asyncio.fixture
async def tls_website(website, tmp_path, monkeypatch):
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    now = datetime.datetime.now(datetime.UTC)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Browser test CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "public.test")])
    leaf = (
        x509.CertificateBuilder()
        .subject_name(leaf_name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("public.test")]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    ca_file, cert_file, key_file = (
        tmp_path / "ca.pem",
        tmp_path / "leaf.pem",
        tmp_path / "key.pem",
    )
    ca_file.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_file.write_bytes(
        leaf.public_bytes(serialization.Encoding.PEM)
        + ca.public_bytes(serialization.Encoding.PEM)
    )
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    home = tmp_path / "home"
    # Chromium's Linux NSS store location changed in recent releases. Both stores
    # contain this test CA; certificate/hostname verification stays enabled.
    for relative in (".pki/nssdb", ".local/share/pki/nssdb"):
        db = home / relative
        db.mkdir(parents=True)
        result = await asyncio.create_subprocess_exec(
            "certutil",
            "-N",
            "--empty-password",
            "-d",
            "sql:" + str(db),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, error = await result.communicate()
        assert result.returncode == 0, error.decode()
        result = await asyncio.create_subprocess_exec(
            "certutil",
            "-A",
            "-d",
            "sql:" + str(db),
            "-n",
            "browser-fixture",
            "-t",
            "C,,",
            "-i",
            str(ca_file),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, error = await result.communicate()
        assert result.returncode == 0, error.decode()
    monkeypatch.setenv("HOME", str(home))
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert_file, key_file)
    sni, hits = [], []
    tls.set_servername_callback(lambda sock, host, context: sni.append(host))

    async def handle(request):
        hits.append((request.host, request.path))
        if request.path == "/ws":
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.send_str("protected-wss")
            async for _ in ws:
                pass
            return ws
        return web.Response(
            text=f"<html><body><main>{WORDS}</main></body></html>",
            content_type="text/html",
        )

    application = web.Application()
    application.router.add_route("*", "/{path:.*}", handle)
    runner = web.AppRunner(application)
    await runner.setup()
    listener = web.TCPSite(runner, "0.0.0.0", 0, ssl_context=tls)
    await listener.start()
    port = listener._server.sockets[0].getsockname()[1]
    try:
        yield port, sni, hits
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_chromium_connect_preserves_tls_sni_and_certificate_validation(
    tls_website,
):
    port, sni, hits = tls_website
    async with SafeBrowser(config=BrowserConfig(ignore_https_errors=True)) as browser:
        page = await browser.crawler.crawler_strategy.browser_manager.browser.new_page()
        response = await page.goto(f"https://public.test:{port}/tls")
        assert response.status == 200
        assert sni[0] == "public.test"
        assert hits[0] == (f"public.test:{port}", "/tls")
        assert any(ip == PUBLIC_IP for _, ip, _ in browser.broker.connections)
        with pytest.raises(PlaywrightError, match="CERT"):
            await page.goto(f"https://wrong.test:{port}/invalid")
        assert not any(path == "/invalid" for _, path in hits)


@pytest.mark.asyncio
async def test_chromium_secure_websocket_uses_validated_connect(tls_website):
    port, _, _ = tls_website
    async with SafeBrowser() as browser:
        page = await browser.crawler.crawler_strategy.browser_manager.browser.new_page()
        await page.goto(f"https://public.test:{port}/tls")
        message = await page.evaluate(
            """url => new Promise((resolve,reject)=>{
          const socket=new WebSocket(url);socket.onmessage=e=>{resolve(e.data);socket.close();};socket.onerror=reject;
        })""",
            f"wss://public.test:{port}/ws",
        )
        assert message == "protected-wss"


@pytest.mark.parametrize("host", ["127.0.0.1", PRIVATE_IP, METADATA_IP])
@pytest.mark.asyncio
async def test_chromium_private_https_is_rejected_before_tls_connect(tls_website, host):
    port, sni, hits = tls_website
    async with SafeBrowser() as browser:
        page = await browser.crawler.crawler_strategy.browser_manager.browser.new_page()
        await rejected_navigation(page, f"https://{host}:{port}/sink")
        assert browser.broker.rejections
        assert not sni and not hits

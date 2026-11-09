"""Raw proxy clients must encounter the same policy as Chromium."""

import asyncio
import socket
import tempfile
from pathlib import Path

import pytest

from hawki_crawler.runtime import browser, egress


@pytest.fixture
def broker_path():
    with tempfile.TemporaryDirectory(prefix="broker-", dir="/tmp") as directory:
        yield str(Path(directory) / "broker.sock")


@pytest.mark.parametrize(
    "target",
    [
        "localhost:443",
        "127.0.0.1:443",
        "10.0.0.1:443",
        "169.254.169.254:443",
        "[::1]:443",
        "[fd00::1]:443",
        "[fe80::1]:443",
        "0.0.0.0:443",
        "user@public.example:443",
        "public.example:443/ignored",
    ],
)
@pytest.mark.asyncio
async def test_connect_rejection_precedes_socket_creation(
    broker_path, monkeypatch, target
):
    sockets = []
    monkeypatch.setattr(egress, "public_socket", lambda info: sockets.append(info))
    broker = egress.EgressBroker()
    path = broker_path
    await broker.start(path)
    reader, writer = await asyncio.open_unix_connection(path)
    try:
        writer.write(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
        await writer.drain()
        response = await reader.read()
        assert b"403 Forbidden" in response
        assert not sockets
    finally:
        await egress.close_writer(writer)
        await broker.close()


@pytest.mark.asyncio
async def test_connect_private_dns_answer_cannot_create_socket(
    broker_path, monkeypatch
):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))
        ],
    )
    sockets = []
    monkeypatch.setattr(egress, "public_socket", lambda info: sockets.append(info))
    broker = egress.EgressBroker()
    path = broker_path
    await broker.start(path)
    reader, writer = await asyncio.open_unix_connection(path)
    try:
        writer.write(
            b"CONNECT rebind.example:443 HTTP/1.1\r\nHost: rebind.example:443\r\n\r\n"
        )
        await writer.drain()
        assert b"403 Forbidden" in await reader.read()
        assert not sockets
    finally:
        await egress.close_writer(writer)
        await broker.close()


@pytest.mark.asyncio
async def test_broker_initialization_failure_never_launches_browser(monkeypatch):
    monkeypatch.setattr(browser, "linux_namespaces_available", lambda: True)

    async def unavailable(*args):
        raise OSError("broker unavailable")

    monkeypatch.setattr(egress.EgressBroker, "start", unavailable)
    protected = browser.SafeBrowser()
    with pytest.raises(browser.BrowserTransportUnavailable, match="broker unavailable"):
        async with protected:
            pytest.fail("Failed broker admitted a browser")
    assert protected.process is None and protected.closed

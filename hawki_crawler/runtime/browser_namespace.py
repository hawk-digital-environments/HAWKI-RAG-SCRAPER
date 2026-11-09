"""Linux browser child in user/net/PID namespaces; PID 1 owns all descendants.

Only loopback exists. An AF_UNIX bridge is the only path to the validating
broker outside this namespace. CDP is a separate local control channel.
"""

import asyncio
import ctypes
import fcntl
import json
import os
import socket
import struct
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

from .egress import close_writer, relay


def isolate_check(parent_netns, parent_pidns):
    netns = os.stat("/proc/self/ns/net").st_ino
    pidns = os.stat("/proc/self/ns/pid").st_ino
    if netns == parent_netns or pidns == parent_pidns or os.getpid() != 1:
        raise RuntimeError("Browser namespace isolation was not established")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as control:
        # Some kernels create dormant tunnel devices in every fresh namespace.
        # None may be UP, and Chromium loses the capabilities needed to alter them.
        for _, name in socket.if_nameindex():
            flags = struct.unpack(
                "16sH14x",
                fcntl.ioctl(control, 0x8913, struct.pack("16sH14x", name.encode(), 0)),
            )[1]
            if name != "lo" and flags & 1:
                raise RuntimeError("Browser namespace has an active external interface")
        request = struct.pack("16sH14x", b"lo", 0)
        flags = struct.unpack("16sH14x", fcntl.ioctl(control, 0x8913, request))[1]
        fcntl.ioctl(control, 0x8914, struct.pack("16sH14x", b"lo", flags | 1))
    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex(("1.1.1.1", 443)) not in {101, 113}:
            raise RuntimeError("Browser namespace unexpectedly has an external route")
    libc = ctypes.CDLL(None, use_errno=True)
    # Prevent uid 0 in this unprivileged user namespace regaining capabilities
    # on exec, then remove every permitted/effective/inheritable capability.
    if libc.prctl(28, 3, 0, 0, 0) or libc.prctl(38, 1, 0, 0, 0):
        raise OSError(ctypes.get_errno(), "Cannot lock browser privilege restriction")
    header = (ctypes.c_uint32 * 2)(0x20080522, 0)
    data = (ctypes.c_uint32 * 6)()
    if libc.capset(header, data):
        raise OSError(ctypes.get_errno(), "Cannot drop browser capabilities")
    return {"netns": netns, "pidns": pidns, "pid": os.getpid(), "interfaces": ["lo"]}


async def main(broker_path, control_path, parent_netns, parent_pidns):
    proof = isolate_check(int(parent_netns), int(parent_pidns))
    bridges = set()

    async def bridge(reader, writer, *, unix=None, port=None):
        task = asyncio.current_task()
        bridges.add(task)
        try:
            remote_reader, remote_writer = (
                await asyncio.open_unix_connection(unix)
                if unix
                else await asyncio.open_connection("127.0.0.1", port)
            )
            await relay(reader, writer, remote_reader, remote_writer)
        except (OSError, ConnectionError):
            await close_writer(writer)
        finally:
            bridges.discard(task)

    proxy = await asyncio.start_server(
        lambda r, w: bridge(r, w, unix=broker_path), "127.0.0.1", 0
    )
    proxy_port = proxy.sockets[0].getsockname()[1]
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        executable = playwright.chromium.executable_path
    with tempfile.TemporaryDirectory(
        prefix="chromium-", dir=str(Path(control_path).parent)
    ) as profile:
        process = await asyncio.create_subprocess_exec(
            executable,
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=0",
            "--user-data-dir=" + profile,
            f"--proxy-server=http://127.0.0.1:{proxy_port}",
            "--proxy-bypass-list=<-loopback>",
            "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
            "--disable-quic",
            "--dns-prefetch-disable",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-sync",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-features=DnsOverHttps,MediaRouter,OptimizationHints,PreconnectToSearch",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            "about:blank",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=sys.stderr,
            close_fds=True,
        )
        control = None
        try:
            active_port = Path(profile) / "DevToolsActivePort"
            for _ in range(600):
                if process.returncode is not None:
                    raise RuntimeError("Isolated Chromium exited during startup")
                if active_port.exists():
                    lines = active_port.read_text().splitlines()
                    if len(lines) >= 2:
                        break
                await asyncio.sleep(0.05)
            else:
                raise RuntimeError("Isolated Chromium CDP startup timed out")
            cdp_port = int(lines[0])
            control = await asyncio.start_unix_server(
                lambda r, w: bridge(r, w, port=cdp_port), control_path
            )
            print(
                json.dumps({**proof, "proxy_port": proxy_port, "cdp_path": lines[1]}),
                flush=True,
            )
            stdin = asyncio.StreamReader()
            transport, _ = await asyncio.get_running_loop().connect_read_pipe(
                lambda: asyncio.StreamReaderProtocol(stdin), sys.stdin.buffer
            )
            waits = [
                asyncio.create_task(stdin.read(1)),
                asyncio.create_task(process.wait()),
            ]
            try:
                await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
            finally:
                transport.close()
                for task in waits:
                    task.cancel()
                await asyncio.gather(*waits, return_exceptions=True)
        finally:
            if process.returncode is None:
                process.kill()
            proxy.close()
            if control:
                control.close()
            for task in list(bridges):
                task.cancel()
            await asyncio.gather(*bridges, return_exceptions=True)
            await proxy.wait_closed()
            if control:
                await control.wait_closed()
            with suppress(ProcessLookupError):
                await process.wait()


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:]))

"""Crawl4AI attaches only to Chromium inside an isolated Linux network namespace."""

import asyncio
import json
import os
import sys
import tempfile
from collections import deque
from pathlib import Path

from .egress import EgressBroker, close_writer, relay
from .network import approve_url
from .scope import current_scope


class BrowserTransportUnavailable(RuntimeError):
    pass


def linux_namespaces_available():
    return sys.platform == "linux" and Path("/usr/bin/unshare").is_file()


class SafeBrowser:
    def __init__(self, config=None):
        if not linux_namespaces_available():
            raise BrowserTransportUnavailable(
                "Protected Chromium requires Linux user/network/PID namespaces. No browser was launched."
            )
        self.config = config
        self.broker = EgressBroker()
        self.process = None
        self.crawler = None
        self.control = None
        self.handlers = set()
        self.stderr = deque(maxlen=20)
        self.stderr_task = None
        self.directory = None
        self.closed = False
        self.close_task = None
        self.scope = current_scope.get()
        scope = current_scope.get()
        if scope:
            if scope.closed or scope.stopping:
                raise BrowserTransportUnavailable("Browser admission is closed")
            scope.sessions.add(self)

    async def __aenter__(self):
        try:
            self.directory = tempfile.TemporaryDirectory(prefix="cce-", dir="/tmp")
            root = Path(self.directory.name)
            broker_path, control_path = root / "egress.sock", root / "control.sock"
            await self.broker.start(str(broker_path))
            self.process = await asyncio.create_subprocess_exec(
                "/usr/bin/unshare",
                "--user",
                "--map-root-user",
                "--net",
                "--pid",
                "--fork",
                "--kill-child=KILL",
                sys.executable,
                "-m",
                "hawki_crawler.runtime.browser_namespace",
                str(broker_path),
                str(control_path),
                str(os.stat("/proc/self/ns/net").st_ino),
                str(os.stat("/proc/self/ns/pid").st_ino),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                close_fds=True,
            )

            async def read_errors():
                while line := await self.process.stderr.readline():
                    self.stderr.append(line.decode(errors="replace").strip())

            self.stderr_task = asyncio.create_task(read_errors())
            line = await asyncio.wait_for(self.process.stdout.readline(), 45)
            if not line:
                await self.process.wait()
                await self.stderr_task
                raise RuntimeError("; ".join(self.stderr))
            self.proof = json.loads(line)

            async def control_connection(reader, writer):
                task = asyncio.current_task()
                self.handlers.add(task)
                try:
                    remote_reader, remote_writer = await asyncio.open_unix_connection(
                        control_path
                    )
                    await relay(reader, writer, remote_reader, remote_writer)
                finally:
                    await close_writer(writer)
                    self.handlers.discard(task)

            self.control = await asyncio.start_server(
                control_connection, "127.0.0.1", 0
            )
            port = self.control.sockets[0].getsockname()[1]
            from crawl4ai import AsyncWebCrawler
            from crawl4ai.async_configs import BrowserConfig
            from crawl4ai.async_crawler_strategy import AsyncPlaywrightCrawlerStrategy
            from crawl4ai.browser_manager import BrowserManager

            config = (self.config or BrowserConfig()).clone(
                browser_type="chromium",
                browser_mode="builtin",
                use_managed_browser=True,
                cdp_url=f"ws://127.0.0.1:{port}" + self.proof["cdp_path"],
                use_persistent_context=False,
                cache_cdp_connection=False,
                create_isolated_context=True,
                cdp_cleanup_on_close=True,
                cdp_close_delay=0,
                ignore_https_errors=False,
                accept_downloads=False,
                max_pages_before_recycle=0,
                proxy=None,
                proxy_config={"server": f"http://127.0.0.1:{self.proof['proxy_port']}"},
            )
            endpoint = config.cdp_url

            class CDPOnlyManager(BrowserManager):
                async def start(manager):
                    if (
                        manager.config.cdp_url != endpoint
                        or manager.config.use_persistent_context
                    ):
                        raise BrowserTransportUnavailable(
                            "Unprotected browser launch is forbidden"
                        )
                    await super().start()

                def _build_browser_args(manager):
                    raise BrowserTransportUnavailable(
                        "Unprotected browser launch is forbidden"
                    )

            strategy = AsyncPlaywrightCrawlerStrategy(browser_config=config)
            strategy.browser_manager = CDPOnlyManager(config, logger=strategy.logger)
            self.crawler = AsyncWebCrawler(config=config, crawler_strategy=strategy)
            await self.crawler.__aenter__()
            return self
        except BaseException as exc:
            await self.close()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise BrowserTransportUnavailable(
                "Protected Chromium initialization failed; Linux unprivileged user/net/PID namespaces "
                "and installed Chromium are required. No browser was launched outside isolation. "
                + str(exc)
            ) from exc

    def admitted(self):
        scope = self.scope
        if (
            self.closed
            or self.broker.closed
            or self.broker.closing
            or self.process.returncode is not None
            or (scope and scope.stopping)
        ):
            raise BrowserTransportUnavailable(
                "Protected browser boundary is unavailable"
            )

    async def arun(self, url, config=None, **kwargs):
        self.admitted()
        approve_url(url)
        return await self.crawler.arun(url=url, config=config, **kwargs)

    async def arun_many(self, urls, config=None, **kwargs):
        self.admitted()
        for url in urls:
            approve_url(url)
        return await self.crawler.arun_many(urls, config=config, **kwargs)

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        if self.closed:
            return
        if self.close_task is None:
            self.close_task = asyncio.create_task(self._close())
        await asyncio.shield(self.close_task)

    async def _close(self):
        # Stop the namespace first: pending navigations and proxy requests must
        # not keep graceful CDP cleanup waiting on an unresponsive target.
        if self.process:
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.control:
            self.control.close()
        for task in list(self.handlers):
            task.cancel()
        await asyncio.gather(*self.handlers, return_exceptions=True)
        if self.control:
            await self.control.wait_closed()
        await self.broker.close()
        if self.crawler:
            from playwright.async_api import Error as PlaywrightError

            manager = self.crawler.crawler_strategy.browser_manager
            try:
                await asyncio.wait_for(self.crawler.close(), 5)
            except (TimeoutError, PlaywrightError):
                # The browser was deliberately terminated. Always stop the
                # remaining Playwright driver explicitly before claiming closed.
                pass
            finally:
                if manager.playwright is not None:
                    await asyncio.wait_for(manager.playwright.stop(), 5)
                    manager.playwright = None
            self.crawler = None
        if self.stderr_task:
            await self.stderr_task
        if self.directory:
            self.directory.cleanup()
        self.closed = True

import asyncio
import time
from typing import Dict, Optional, TYPE_CHECKING

from crawl4ai.async_configs import CacheMode, CrawlerRunConfig

from hawki_crawler.crawler.assets.asset_policy import AssetPolicy
from hawki_crawler.crawler.storage.page_data_store import PageDataStore

if TYPE_CHECKING:
    from hawki_crawler.crawler.core.protocols import ServiceCrawlRuntimeMixinProtocol


class ServiceCrawlRuntimeMixin:
    """Runtime helpers used while a crawl job is active.

    These methods do not decide which URLs to crawl. They support the running
    job by classifying URL types, stopping safely, restarting browser work when
    needed, tracking memory pressure, and writing crawl output to storage.
    """

    def looks_like_file_url(self: "ServiceCrawlRuntimeMixinProtocol", url: str) -> bool:
        """Return True for URLs that should be downloaded instead of rendered."""
        return AssetPolicy().looks_like_file_url(url)

    def _page_data_store(self: "ServiceCrawlRuntimeMixinProtocol") -> PageDataStore:
        return PageDataStore(
            storage_manager=getattr(self, "storage_manager", None),
            create_page_directory=self.create_page_directory,
            skip_images=getattr(self.config, "skip_images", False),
        )

    def build_run_config(self: "ServiceCrawlRuntimeMixinProtocol") -> CrawlerRunConfig:
        """Build the shared Crawl4AI run config for single-page and batch crawls."""
        return CrawlerRunConfig(
            word_count_threshold=0,
            exclude_external_links=False,
            process_iframes=False,
            remove_overlay_elements=True,
            cache_mode=CacheMode.BYPASS,
            wait_until=self.config.wait_until,
            page_timeout=self.config.page_timeout_ms,
            delay_before_return_html=5.0
        )

    async def trigger_safe_stop(self: "ServiceCrawlRuntimeMixinProtocol", reason: str) -> None:
        """Stop future crawl work and remember why the job was aborted."""
        async with self.abort_lock:
            if self.abort_crawl:
                return
            self.abort_crawl = True
            self.abort_reason = reason
            # Clearing the queue prevents new URLs from being scheduled after a fatal condition.
            self.to_visit.clear()

    async def _request_browser_restart(self: "ServiceCrawlRuntimeMixinProtocol", url: str) -> None:
        """Ask the outer crawl loop to restart the browser before retrying a URL."""
        if not self.enable_browser_restarts:
            return
        async with self.restart_lock:
            if url not in self.restart_urls:
                self.restart_urls.append(url)
            self.restart_crawler = True
            self.restart_reason = "browser_closed"

    def get_memory_usage_ratio(self: "ServiceCrawlRuntimeMixinProtocol") -> Optional[float]:
        """Return memory usage ratio based on cgroup limits, or None if unavailable."""
        paths = [
            ("/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory.max"),
            ("/sys/fs/cgroup/memory/memory.usage_in_bytes", "/sys/fs/cgroup/memory/memory.limit_in_bytes"),
        ]
        for current_path, max_path in paths:
            try:
                with open(current_path, "r", encoding="utf-8") as f:
                    current = f.read().strip()
                with open(max_path, "r", encoding="utf-8") as f:
                    limit = f.read().strip()
                if limit == "max":
                    return None
                current_val = float(current)
                limit_val = float(limit)
                if limit_val <= 0:
                    return None
                return current_val / limit_val
            except Exception:
                continue
        return None

    async def wait_for_memory_relief(self: "ServiceCrawlRuntimeMixinProtocol") -> None:
        """Wait for container memory usage to drop before restarting browser work."""
        if not self.enable_memory_watchdog:
            return
        deadline = time.monotonic() + self.memory_restart_wait_seconds
        while True:
            ratio = self.get_memory_usage_ratio()
            if ratio is None or ratio <= self.memory_resume_threshold:
                return
            if time.monotonic() >= deadline:
                self.job_logger.error(
                    "memory watchdog timeout: usage %.1f%% still above resume threshold",
                    ratio * 100 if ratio is not None else -1,
                )
                return
            await asyncio.sleep(5)

    async def update_total_urls(self: "ServiceCrawlRuntimeMixinProtocol", new_total: int) -> None:
        """Increase total URL counts when discovery finds more work."""
        if new_total <= 0:
            return
        if self.job_state:
            snapshot = await self.job_state.get_snapshot()
            if new_total > snapshot.total_urls:
                await self.job_state.set_total_urls(new_total)
        if self.progress_tracker:
            progress = await self.progress_tracker.get_progress()
            if new_total > progress["total_urls"]:
                await self.progress_tracker.set_total_urls(new_total)

    async def save_page_data(
        self: "ServiceCrawlRuntimeMixinProtocol",
        page_data: Dict,
        page_number: int,
        url_hash: str
    ):
        """Persist page metadata/content and optional diagnostics."""
        await self._page_data_store().save_page_data(page_data, page_number, url_hash)

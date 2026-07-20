from typing import Dict, Optional, TYPE_CHECKING

from crawl4ai.async_configs import CrawlerRunConfig

from hawki_crawler.crawler.core.runtime.control import (
    request_browser_restart,
    request_safe_stop,
    update_total_url_counts,
)
from hawki_crawler.crawler.core.runtime.memory_watchdog import (
    read_cgroup_memory_usage_ratio,
    wait_until_memory_relief,
)
from hawki_crawler.crawler.core.runtime.run_config import build_crawler_run_config
from hawki_crawler.crawler.storage.page_data_store import PageDataStore

if TYPE_CHECKING:
    from hawki_crawler.crawler.core.protocols import ServiceCrawlRuntimeMixinProtocol


class ServiceCrawlRuntimeMixin:
    """Runtime helpers used while a crawl job is active.

    These methods do not decide which URLs to crawl. They support the running
    job by stopping safely, restarting browser work when needed, tracking
    memory pressure, and writing crawl output to storage.
    """

    def _page_data_store(self: "ServiceCrawlRuntimeMixinProtocol") -> PageDataStore:
        return PageDataStore(
            storage_manager=getattr(self, "storage_manager", None),
            create_page_directory=self.create_page_directory,
            skip_images=getattr(self.config, "skip_images", False),
        )

    def build_run_config(self: "ServiceCrawlRuntimeMixinProtocol") -> CrawlerRunConfig:
        """Build the shared Crawl4AI run config for single-page and batch crawls."""
        return build_crawler_run_config(self.config)

    async def trigger_safe_stop(self: "ServiceCrawlRuntimeMixinProtocol", reason: str) -> None:
        """Stop future crawl work and remember why the job was aborted."""
        def mark_aborted(abort_reason: str) -> None:
            self.abort_crawl = True
            self.abort_reason = abort_reason

        await request_safe_stop(
            abort_lock=self.abort_lock,
            is_aborted=lambda: self.abort_crawl,
            mark_aborted=mark_aborted,
            pending_urls=self.to_visit,
            reason=reason,
        )

    async def _request_browser_restart(self: "ServiceCrawlRuntimeMixinProtocol", url: str) -> None:
        """Ask the outer crawl loop to restart the browser before retrying a URL."""
        def mark_restart_requested(reason: str) -> None:
            self.restart_crawler = True
            self.restart_reason = reason

        await request_browser_restart(
            enabled=self.enable_browser_restarts,
            restart_lock=self.restart_lock,
            restart_urls=self.restart_urls,
            mark_restart_requested=mark_restart_requested,
            url=url,
        )

    def get_memory_usage_ratio(self: "ServiceCrawlRuntimeMixinProtocol") -> Optional[float]:
        """Return memory usage ratio based on cgroup limits, or None if unavailable."""
        return read_cgroup_memory_usage_ratio()

    async def wait_for_memory_relief(self: "ServiceCrawlRuntimeMixinProtocol") -> None:
        """Wait for container memory usage to drop before restarting browser work."""
        await wait_until_memory_relief(
            enable_memory_watchdog=self.enable_memory_watchdog,
            memory_resume_threshold=self.memory_resume_threshold,
            memory_restart_wait_seconds=self.memory_restart_wait_seconds,
            get_memory_usage_ratio=self.get_memory_usage_ratio,
            job_logger=self.job_logger,
        )

    async def update_total_urls(self: "ServiceCrawlRuntimeMixinProtocol", new_total: int) -> None:
        """Increase total URL counts when discovery finds more work."""
        await update_total_url_counts(
            new_total=new_total,
            job_state=self.job_state,
            progress_tracker=self.progress_tracker,
        )

    async def save_page_data(
        self: "ServiceCrawlRuntimeMixinProtocol",
        page_data: Dict,
        page_number: int,
        url_hash: str
    ):
        """Persist page metadata/content and optional diagnostics."""
        await self._page_data_store().save_page_data(page_data, page_number, url_hash)

import asyncio
import json
import time
from typing import Dict, Optional, TYPE_CHECKING
from urllib.parse import urlparse

import aiofiles
from crawl4ai.async_configs import CacheMode, CrawlerRunConfig

from src.crawler.storage.page_output import DIAGNOSTICS_DIRNAME

if TYPE_CHECKING:
    from src.crawler.core.protocols import CrawlerServiceProtocol


class ServiceCrawlRuntimeMixin:
    """Runtime helpers used while a crawl job is active.

    These methods do not decide which URLs to crawl. They support the running
    job by classifying URL types, stopping safely, restarting browser work when
    needed, tracking memory pressure, and writing crawl output to storage.
    """

    def looks_like_file_url(self: "CrawlerServiceProtocol", url: str) -> bool:
        """Return True for URLs that should be downloaded instead of rendered."""
        parsed = urlparse(url)
        path = parsed.path.lower()
        if path.endswith(".exe"):
            return True
        if path.endswith(".pdf"):
            return True
        extensions = (
            ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods",
            ".odp", ".rtf", ".txt", ".csv", ".zip", ".rar", ".7z"
        )
        if path.endswith(extensions):
            return True
        if "/media/" in path and not path.endswith(".pdf"):
            return True
        return False

    def build_run_config(self: "CrawlerServiceProtocol") -> CrawlerRunConfig:
        """Build the shared Crawl4AI run config for single-page and batch crawls."""
        return CrawlerRunConfig(
            word_count_threshold=0,
            exclude_external_links=False,
            process_iframes=False,
            remove_overlay_elements=False,
            cache_mode=CacheMode.BYPASS,
            wait_until=self.config.wait_until,
            page_timeout=self.config.page_timeout_ms,
            delay_before_return_html=5.0
        )

    async def trigger_safe_stop(self: "CrawlerServiceProtocol", reason: str) -> None:
        """Stop future crawl work and remember why the job was aborted."""
        async with self.abort_lock:
            if self.abort_crawl:
                return
            self.abort_crawl = True
            self.abort_reason = reason
            # Clearing the queue prevents new URLs from being scheduled after a fatal condition.
            self.to_visit.clear()

    async def _request_browser_restart(self: "CrawlerServiceProtocol", url: str) -> None:
        """Ask the outer crawl loop to restart the browser before retrying a URL."""
        if not self.enable_browser_restarts:
            return
        async with self.restart_lock:
            if url not in self.restart_urls:
                self.restart_urls.append(url)
            self.restart_crawler = True
            self.restart_reason = "browser_closed"

    def get_memory_usage_ratio(self: "CrawlerServiceProtocol") -> Optional[float]:
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

    async def wait_for_memory_relief(self: "CrawlerServiceProtocol") -> None:
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

    async def update_total_urls(self: "CrawlerServiceProtocol", new_total: int) -> None:
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
        self: "CrawlerServiceProtocol",
        page_data: Dict,
        page_number: int,
        url_hash: str
    ):
        """Persist page metadata/content and optional diagnostics.

        Newer jobs store pages by URL hash so the same URL has a stable output
        location. The page-number fallback is only for runs without a storage
        manager, such as lightweight local tests.
        """
        low_quality_content = page_data.get('low_quality_content')
        raw_html = page_data.get('html_content')
        # Keep raw HTML when extraction produced weak or empty markdown; it helps debug bad pages later.
        should_save_raw = bool(raw_html) and (low_quality_content or not page_data.get('markdown'))
        if self.storage_manager:
            # Preferred path: save under the URL hash directory.
            self.storage_manager.create_hash_directory(url_hash, create_images_dir=not self.config.skip_images)
            await self.storage_manager.save_hash_json(url_hash, page_data['data'])
            await self.storage_manager.save_hash_content(url_hash, page_data['markdown'] if page_data['markdown'] else "")
            await self.storage_manager.upsert_completed_url_record(page_data['data'], url_hash=url_hash)
            if low_quality_content:
                diagnostics_dir = self.storage_manager.get_hash_directory(url_hash) / DIAGNOSTICS_DIRNAME
                diagnostics_dir.mkdir(exist_ok=True)
                low_q_file = diagnostics_dir / "low_q.txt"
                async with aiofiles.open(low_q_file, 'w', encoding='utf-8') as f:
                    await f.write(low_quality_content)
            if should_save_raw:
                diagnostics_dir = self.storage_manager.get_hash_directory(url_hash) / DIAGNOSTICS_DIRNAME
                diagnostics_dir.mkdir(exist_ok=True)
                raw_file = diagnostics_dir / "raw.html"
                async with aiofiles.open(raw_file, 'w', encoding='utf-8') as f:
                    await f.write(raw_html)
        else:
            # Last-resort path for simple/local runs without the storage manager abstraction.
            page_dir = await self.create_page_directory(page_number)
            json_filename = page_dir / "data.json"
            async with aiofiles.open(json_filename, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(page_data['data'], indent=2, ensure_ascii=False, allow_nan=False))

            md_filename = page_dir / "content.md"
            async with aiofiles.open(md_filename, 'w', encoding='utf-8') as f:
                await f.write(page_data['markdown'] if page_data['markdown'] else "")
            if low_quality_content:
                diagnostics_dir = page_dir / DIAGNOSTICS_DIRNAME
                diagnostics_dir.mkdir(exist_ok=True)
                low_q_file = diagnostics_dir / "low_q.txt"
                async with aiofiles.open(low_q_file, 'w', encoding='utf-8') as f:
                    await f.write(low_quality_content)
            if should_save_raw:
                diagnostics_dir = page_dir / DIAGNOSTICS_DIRNAME
                diagnostics_dir.mkdir(exist_ok=True)
                raw_file = diagnostics_dir / "raw.html"
                async with aiofiles.open(raw_file, 'w', encoding='utf-8') as f:
                    await f.write(raw_html)

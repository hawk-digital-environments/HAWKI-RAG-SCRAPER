"""Structural contracts for crawler mixins.

The crawler service is assembled from mixins. These protocols document the
attributes and cross-mixin methods that each mixin expects on ``self`` without
changing the runtime inheritance model.
"""


from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple

import aiohttp
from crawl4ai.async_configs import CrawlerRunConfig

from hawki_crawler.crawler.communication.interface import Stage
from hawki_crawler.crawler.models import CrawlConfig


class CrawlerServiceProtocol(Protocol):
    """Expected shape of the fully assembled crawler service.

    Individual mixins use attributes and methods that are initialized or defined
    elsewhere on CrawlerService. This protocol lists those shared dependencies so
    the mixin contract is visible to readers and static type checkers.
    """

    config: CrawlConfig
    visited_urls: Set[str]
    to_visit: List[str]
    url_depth: Dict[str, int]
    url_source: Dict[str, str]
    sitemap_lastmod: Dict[str, str]
    pages_data: List[Dict[str, Any]]
    rate_limiter: Any
    semaphore: asyncio.Semaphore
    page_counter: int
    counter_lock: asyncio.Lock
    allow_over_max_pages: bool
    abort_crawl: bool
    abort_reason: Optional[str]
    abort_lock: asyncio.Lock
    pause_event: Optional[asyncio.Event]
    pause_logged: bool
    consecutive_5xx: int
    consecutive_5xx_lock: asyncio.Lock
    restart_crawler: bool
    restart_urls: List[str]
    restart_lock: asyncio.Lock
    browser_restart_count: int
    max_browser_restarts: int
    browser_restart_interval_seconds: int
    browser_last_restart: float
    enable_browser_restarts: bool
    enable_memory_watchdog: bool
    memory_restart_threshold: float
    memory_resume_threshold: float
    memory_restart_wait_seconds: int
    restart_reason: Optional[str]
    communication_service: Any
    job_state: Any
    storage_manager: Any
    job_id: Optional[str]
    job_logger: logging.LoggerAdapter
    site_profile: Dict[str, Any]
    progress_tracker: Any
    url_tracking_manager: Any
    summary_manager: Any
    file_event_publisher: Any
    http_session: Optional[aiohttp.ClientSession]
    sitemap_path: Optional[str]
    sitemap_map: Dict[str, Dict[str, Any]]
    sitemap_urls: List[str]
    sitemap_base: Optional[str]
    crawl_host: Optional[str]
    headers: Dict[str, str]
    output_dir: Path

    async def setup_directories(self) -> None: ...
    async def create_page_directory(self, page_number: int, create_files_dir: bool = False) -> Path: ...
    def normalize_url(self, url: str) -> str: ...

    async def send_stage(self, stage: Stage, details: Optional[Dict[str, Any]] = None) -> None: ...
    async def send_report_progress(self, progress_data: Dict[str, Any]) -> None: ...
    async def send_summary(self, summary_data: Dict[str, Any]) -> None: ...

    def get_forbidden_hosts(self) -> Set[str]: ...
    def is_forbidden_url(self, url: str) -> bool: ...
    def is_discovery_url_allowed(self, url: str) -> bool: ...
    def is_video_url(self, url: str) -> bool: ...

    def load_sitemap_map(self, path: str) -> Dict[str, Dict[str, Any]]: ...
    def load_sitemap_urls(self, path: str) -> List[str]: ...
    def lookup_sitemap_entry(self, url: str) -> Optional[Dict[str, Any]]: ...
    def first_sitemap_entry(self, *urls: str) -> Optional[Dict[str, Any]]: ...
    def get_sitemap_date(self, entry: Optional[Dict[str, Any]]) -> Optional[str]: ...
    def parse_http_date(self, date_str: Optional[str]) -> Optional[str]: ...
    async def run_sitemap_scrape(self) -> None: ...
    async def is_sitemap(self, url: str) -> bool: ...
    async def parse_sitemap(self, sitemap_url: str) -> List[str]: ...
    async def discover_urls(self, html_content: str, base_url: str) -> List[str]: ...

    async def fetch_head(self, url: str) -> Tuple[Optional[int], Dict[str, str]]: ...
    async def is_pdf_resource(
        self,
        url: str,
        head_status: Optional[int] = None,
        head_headers: Optional[Dict[str, str]] = None,
    ) -> bool: ...
    async def is_file_resource(
        self,
        url: str,
        head_status: Optional[int] = None,
        head_headers: Optional[Dict[str, str]] = None,
    ) -> bool: ...
    async def fetch_and_save_pdf(self, *args: Any, **kwargs: Any) -> Optional[Dict[str, str]]: ...
    async def fetch_and_save_file(self, *args: Any, **kwargs: Any) -> Optional[Dict[str, str]]: ...
    def extract_pdf_links(self, html_content: str, base_url: str) -> List[str]: ...
    def extract_file_links(self, html_content: str, base_url: str) -> List[str]: ...

    def build_run_config(self) -> CrawlerRunConfig: ...
    def detect_language(self, *args: Any, **kwargs: Any) -> str: ...
    async def extract_page_data(self, *args: Any, **kwargs: Any) -> Optional[Dict[str, Any]]: ...
    async def save_page_data(
        self,
        page_data: Dict[str, Any],
        page_number: int,
        url_hash: str,
    ) -> None: ...

    async def trigger_safe_stop(self, reason: str) -> None: ...
    def get_memory_usage_ratio(self) -> Optional[float]: ...
    async def wait_for_memory_relief(self) -> None: ...
    async def update_total_urls(self, new_total: int) -> None: ...
    def looks_like_file_url(self, url: str) -> bool: ...

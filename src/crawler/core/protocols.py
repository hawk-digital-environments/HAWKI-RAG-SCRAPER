"""Structural contracts for crawler service mixins.

The crawler service is assembled from mixins. Each protocol below documents the
attributes and cross-mixin methods that one mixin expects on ``self``. The final
``CrawlerService`` still provides all of these members at runtime through normal
multiple inheritance; the protocols make those service-to-service dependencies
explicit for readers and static type checkers.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple

import aiohttp
from crawl4ai.async_configs import CrawlerRunConfig

from hawki_crawler.crawler.communication.progress_publisher import ProgressPublisher
from hawki_crawler.crawler.models import CrawlConfig
from hawki_crawler.crawler.parsing.date_language import DateLanguageService
from hawki_crawler.crawler.policies.url_policy import UrlPolicyService
from hawki_crawler.crawler.sitemap.service import SitemapService


class ServiceSitemapMixinProtocol(Protocol):
    """Dependencies used by sitemap loading, scraping, parsing, and discovery."""

    config: CrawlConfig
    site_profile: Dict[str, Any]
    sitemap_base: Optional[str]
    sitemap_path: Optional[str]
    sitemap_map: Dict[str, Dict[str, Any]]
    sitemap_urls: List[str]
    sitemap_lastmod: Dict[str, str]
    headers: Dict[str, str]
    job_id: Optional[str]
    url_tracking_manager: Any
    url_policy: UrlPolicyService

    def _sitemap_service(self) -> SitemapService: ...
    def _normalize_url_key(self, url: str) -> Optional[str]: ...
    def _normalize_sitemap_meta(self, meta: Any) -> Dict[str, Any]: ...
    def get_sitemap_date(self, entry: Optional[Dict[str, Any]]) -> Optional[str]: ...
    def load_sitemap_map(self, path: str) -> Dict[str, Dict[str, Any]]: ...
    def load_sitemap_urls(self, path: str) -> List[str]: ...
    def lookup_sitemap_entry(self, url: str) -> Optional[Dict[str, Any]]: ...
    def parse_http_date(self, date_str: Optional[str]) -> Optional[str]: ...


class ServiceParseAssetsMixinProtocol(Protocol):
    """Dependencies used by image, PDF, and file extraction/download helpers."""

    config: CrawlConfig
    rate_limiter: Any
    headers: Dict[str, str]
    http_session: Optional[aiohttp.ClientSession]
    storage_manager: Any
    file_event_publisher: Any
    job_id: Optional[str]
    job_logger: logging.LoggerAdapter

    def _asset_logger(self) -> logging.LoggerAdapter | logging.Logger: ...
    async def create_page_directory(self, page_number: int, create_files_dir: bool = False) -> Path: ...
    async def fetch_head(self, url: str) -> Tuple[Optional[int], Dict[str, str]]: ...
    def _filename_from_content_disposition(self, header_value: str) -> Optional[str]: ...
    def _should_skip_file_download(self, url: str, filename: Optional[str], content_type: str) -> bool: ...
    async def _publish_saved_file_event(
        self,
        *,
        file_url: str,
        page_url: Optional[str],
        file_entry: Dict[str, str],
    ) -> None: ...


class ServiceParseContentMixinProtocol(Protocol):
    """Dependencies used while converting rendered HTML into page metadata."""

    config: CrawlConfig
    site_profile: Dict[str, Any]
    progress_tracker: Any
    url_tracking_manager: Any
    storage_manager: Any
    headers: Dict[str, str]
    job_logger: logging.LoggerAdapter
    date_language: DateLanguageService

    def _site_profile_extractors(self) -> Dict[str, List[str]]: ...
    def _fix_mojibake(self, text: str) -> str: ...
    def _extract_result_markdown(self, result: Any) -> str: ...
    def _clean_markdown_output(self, markdown: str, noise_phrases: List[str]) -> Tuple[str, List[str]]: ...
    def first_sitemap_entry(self, *urls: str) -> Optional[Dict[str, Any]]: ...
    def get_sitemap_date(self, entry: Optional[Dict[str, Any]]) -> Optional[str]: ...
    def parse_http_date(self, date_str: Optional[str]) -> Optional[str]: ...
    async def create_page_directory(self, page_number: int, create_files_dir: bool = False) -> Path: ...
    async def download_image(
        self,
        image_url: str,
        session: aiohttp.ClientSession,
        images_dir: Path,
    ) -> Optional[str]: ...


class ServiceCrawlRuntimeMixinProtocol(Protocol):
    """Dependencies used by runtime crawl helpers and persistence."""

    config: CrawlConfig
    to_visit: List[str]
    abort_crawl: bool
    abort_reason: Optional[str]
    abort_lock: asyncio.Lock
    restart_crawler: bool
    restart_urls: List[str]
    restart_lock: asyncio.Lock
    enable_browser_restarts: bool
    enable_memory_watchdog: bool
    memory_resume_threshold: float
    memory_restart_wait_seconds: int
    restart_reason: Optional[str]
    job_state: Any
    progress_tracker: Any
    storage_manager: Any
    job_logger: logging.LoggerAdapter

    async def create_page_directory(self, page_number: int, create_files_dir: bool = False) -> Path: ...
    def get_memory_usage_ratio(self) -> Optional[float]: ...


class ServiceCrawlExecutionMixinProtocol(Protocol):
    """Dependencies used by the high-level crawl orchestration mixin."""

    config: CrawlConfig
    visited_urls: Set[str]
    to_visit: List[str]
    url_depth: Dict[str, int]
    url_source: Dict[str, str]
    semaphore: asyncio.Semaphore
    page_counter: int
    counter_lock: asyncio.Lock
    allow_over_max_pages: bool
    abort_crawl: bool
    abort_reason: Optional[str]
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
    restart_reason: Optional[str]
    job_state: Any
    storage_manager: Any
    job_id: Optional[str]
    job_logger: logging.LoggerAdapter
    progress_tracker: Any
    url_tracking_manager: Any
    summary_manager: Any
    http_session: Optional[aiohttp.ClientSession]
    sitemap_map: Dict[str, Dict[str, Any]]
    sitemap_urls: List[str]
    crawl_host: Optional[str]
    headers: Dict[str, str]
    output_dir: Path
    url_policy: UrlPolicyService
    date_language: DateLanguageService
    progress_publisher: ProgressPublisher

    async def setup_directories(self) -> None: ...
    async def run_sitemap_scrape(self) -> None: ...
    async def is_sitemap(self, url: str) -> bool: ...
    async def parse_sitemap(self, sitemap_url: str) -> List[str]: ...
    async def discover_urls(self, html_content: str, base_url: str) -> List[str]: ...
    def lookup_sitemap_entry(self, url: str) -> Optional[Dict[str, Any]]: ...
    def get_sitemap_date(self, entry: Optional[Dict[str, Any]]) -> Optional[str]: ...
    def parse_http_date(self, date_str: Optional[str]) -> Optional[str]: ...
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
    async def extract_page_data(self, *args: Any, **kwargs: Any) -> Optional[Dict[str, Any]]: ...
    async def save_page_data(self, page_data: Dict[str, Any], page_number: int, url_hash: str) -> None: ...
    async def trigger_safe_stop(self, reason: str) -> None: ...
    def get_memory_usage_ratio(self) -> Optional[float]: ...
    async def wait_for_memory_relief(self) -> None: ...
    async def update_total_urls(self, new_total: int) -> None: ...
    def looks_like_file_url(self, url: str) -> bool: ...
    def _is_pause_requested(self) -> bool: ...
    async def _wait_if_paused(self) -> None: ...


class CrawlerServiceProtocol(
    ServiceSitemapMixinProtocol,
    ServiceParseAssetsMixinProtocol,
    ServiceParseContentMixinProtocol,
    ServiceCrawlRuntimeMixinProtocol,
    ServiceCrawlExecutionMixinProtocol,
    Protocol,
):
    """Combined protocol for code that truly needs the whole crawler service."""

import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Any, Dict, List, Set
from urllib.parse import urlparse, urlunparse

import aiohttp

from hawki_crawler.crawler.models import CrawlConfig
from hawki_crawler.crawler.state.progress_tracker import ProgressTracker
from hawki_crawler.crawler.state.job_state import JobState
from hawki_crawler.crawler.storage.url_tracking_manager import URLTrackingManager
from hawki_crawler.crawler.storage.summary_manager import SummaryManager
from hawki_crawler.crawler.core.service_rate import RateLimiter
from hawki_crawler.crawler.core.sitemap_scraper import DEFAULT_SITEMAP_BASE
from hawki_crawler.crawler.profiles import resolve_site_profile
from hawki_crawler.services.file_event_publisher import FileEventPublisher
from hawki_crawler.common.logging_setup import parse_log_level


class ServiceInitMixin:
    """Initializer and basic setup helpers for CrawlerService."""

    def __init__(
        self,
        config: CrawlConfig,
        job_id: Optional[str] = None,
        communication_service: Optional[Any] = None,
        job_state: Optional[JobState] = None,
        storage_manager: Optional[Any] = None,
        pause_event: Optional[asyncio.Event] = None
    ):
        self.config = config
        self._init_queue_state()
        self._init_crawl_limits(config)
        self._init_stop_and_pause_state(pause_event)
        self._init_browser_restart_state()
        self._init_memory_watchdog_state()
        self._init_external_services(communication_service, job_state, storage_manager, job_id)
        self._init_job_logger()
        self.site_profile = resolve_site_profile(str(config.url), config.site_profile_path)
        self._init_job_helpers(job_id)
        self._init_runtime_clients()
        self._init_sitemap_state()
        self._init_http_headers()
        self._init_output_paths(config)

    def _init_queue_state(self) -> None:
        """State shared by the crawl loop while it decides what to visit next."""
        self.visited_urls: Set[str] = set()
        self.to_visit: List[str] = []
        self.url_depth: Dict[str, int] = {}
        self.url_source: Dict[str, str] = {}
        self.pages_data: List[Dict] = []

    def _init_crawl_limits(self, config: CrawlConfig) -> None:
        """Counters, locks, and rate limits used while pages are being processed."""
        self.rate_limiter = RateLimiter(config.max_rpm, config.request_delay)
        self.semaphore = asyncio.Semaphore(config.max_concurrency)
        self.page_counter = 0
        self.counter_lock = asyncio.Lock()
        self.allow_over_max_pages = False
        self.consecutive_5xx = 0
        self.consecutive_5xx_lock = asyncio.Lock()

    def _init_stop_and_pause_state(self, pause_event: Optional[asyncio.Event]) -> None:
        """Flags used by stop, pause, and resume without losing queued URLs."""
        self.abort_crawl = False
        self.abort_reason: Optional[str] = None
        self.abort_lock = asyncio.Lock()
        self.pause_event = pause_event
        self.pause_logged = False

    def _init_browser_restart_state(self) -> None:
        """Browser-restart bookkeeping owned by the crawl execution mixin."""
        self.restart_crawler = False
        self.restart_urls: List[str] = []
        self.restart_lock = asyncio.Lock()
        self.browser_restart_count = 0
        self.max_browser_restarts = 3
        self.browser_restart_interval_seconds = 3600
        self.browser_last_restart = time.monotonic()
        self.enable_browser_restarts = False
        self.restart_reason: Optional[str] = None

    def _init_memory_watchdog_state(self) -> None:
        """Memory watchdog thresholds used by the runtime mixin."""
        self.enable_memory_watchdog = True
        self.memory_restart_threshold = 0.9
        self.memory_resume_threshold = 0.1
        self.memory_restart_wait_seconds = 300

    def _init_external_services(
        self,
        communication_service: Optional[Any],
        job_state: Optional[JobState],
        storage_manager: Optional[Any],
        job_id: Optional[str],
    ) -> None:
        """References passed in from the API/job layer."""
        self.communication_service = communication_service
        self.job_state = job_state
        self.storage_manager = storage_manager
        self.job_id = job_id

    def _init_job_logger(self) -> None:
        """Start with the shared crawler logger; job file logging may replace it."""
        base_crawler_logger = logging.getLogger("crawler")
        self.job_logger = logging.LoggerAdapter(
            base_crawler_logger,
            {"job_id": self.job_id or "unknown"},
        )

    def _init_job_helpers(self, job_id: Optional[str]) -> None:
        """Create per-job helpers only when a persistent job directory exists."""
        self.progress_tracker = None
        self.url_tracking_manager = None
        self.summary_manager = None
        self.file_event_publisher = None

        base_path = None
        if self.job_id and self.storage_manager:
            base_path = str(self.storage_manager.base_path)
            self.progress_tracker = ProgressTracker(event_emitter=self.communication_service)
            self.url_tracking_manager = URLTrackingManager(
                job_id=job_id,
                base_path=base_path,
                forbidden_hosts=self.site_profile.get("forbidden", {}).get("hosts"),
                forbidden_patterns=self.site_profile.get("forbidden", {}).get("url_patterns"),
                forbidden_rules_file=self.site_profile.get("forbidden", {}).get("rules_file"),
            )
            self.summary_manager = SummaryManager(job_id=job_id, base_path=base_path)
            self.file_event_publisher = FileEventPublisher(
                default_job_id=str(job_id),
                job_base_path=self.storage_manager.get_job_directory(),
            )
            self._setup_job_error_logger()

    def _init_runtime_clients(self) -> None:
        """Clients that are opened lazily and closed after the crawl."""
        self.http_session: Optional[aiohttp.ClientSession] = None

    def _init_sitemap_state(self) -> None:
        """Sitemap input and lookup state used by sitemap-related mixins."""
        self.sitemap_lastmod: Dict[str, str] = {}
        default_sitemap_path = None
        if self.job_id and self.storage_manager:
            default_sitemap_path = str(self.storage_manager.get_job_directory() / "sitemap.json")
        self.sitemap_path = (
            self.config.sitemap_output
            or os.getenv("SITE_SITEMAP_JSON")
            or os.getenv("SITEMAP_JSON")
            or default_sitemap_path
        )
        self.sitemap_map = self.load_sitemap_map(self.sitemap_path)
        self.sitemap_urls = self.load_sitemap_urls(self.sitemap_path)
        profile_sitemap = self.site_profile.get("sitemap", {})
        self.sitemap_base = self.config.sitemap_base or os.getenv("SITEMAP_BASE", profile_sitemap.get("base_url", DEFAULT_SITEMAP_BASE))
        self.crawl_host = urlparse(str(self.config.url)).hostname

    def _init_http_headers(self) -> None:
        """Default request headers used by HTTP and browser fetches."""
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }

    def _init_output_paths(self, config: CrawlConfig) -> None:
        """Resolve the label and output directory after job storage is known."""
        if not config.label:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            domain = urlparse(str(config.url)).netloc.replace(".", "_")
            self.config.label = f"{domain}_{timestamp}"

        if self.storage_manager:
            self.output_dir = self.storage_manager.get_job_directory()
        else:
            self.output_dir = Path(config.output_dir) / self.config.label

    def _setup_job_error_logger(self) -> None:
        if not self.job_id or not self.storage_manager:
            return
        self.storage_manager.ensure_job_directory()
        log_path = self.storage_manager.get_job_directory() / "crawler.log"
        logger = logging.getLogger(f"crawler.{self.job_id}")
        handler_name = f"job_error_file_{self.job_id}"
        for handler in logger.handlers:
            if getattr(handler, "name", "") == handler_name:
                self.job_logger = logging.LoggerAdapter(logger, {"job_id": self.job_id})
                return
        handler = logging.FileHandler(log_path)
        handler.name = handler_name
        handler.setLevel(parse_log_level(os.getenv("JOB_LOG_FILE_LEVEL", "INFO"), logging.INFO))
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s [job_id=%(job_id)s]"
            )
        )
        class _JobContextFilter(logging.Filter):
            def __init__(self, job_id: str) -> None:
                super().__init__()
                self.job_id = job_id

            def filter(self, record: logging.LogRecord) -> bool:
                if not getattr(record, "job_id", None):
                    record.job_id = self.job_id
                return True

        handler.addFilter(_JobContextFilter(self.job_id))
        logger.addHandler(handler)
        logger.propagate = True
        self.job_logger = logging.LoggerAdapter(logger, {"job_id": self.job_id})

    async def setup_directories(self):
        """Create necessary directories"""
        if self.storage_manager:
            self.storage_manager.ensure_job_directory()
        else:
            self.output_dir.mkdir(parents=True, exist_ok=True)

    async def create_page_directory(self, page_number: int, create_files_dir: bool = False) -> Path:
        """Create directory for a specific page"""
        if self.storage_manager:
            return self.storage_manager.create_page_directory(
                page_number,
                create_images_dir=not self.config.skip_images,
                create_files_dir=create_files_dir
            )
        page_dir = self.output_dir / f"page_{page_number:05d}"
        page_dir.mkdir(exist_ok=True)

        if not self.config.skip_images:
            images_dir = page_dir / "images"
            images_dir.mkdir(exist_ok=True)

        if create_files_dir:
            files_dir = page_dir / "files"
            files_dir.mkdir(exist_ok=True)

        return page_dir

    def normalize_url(self, url: str) -> str:
        """Normalize URL by removing fragments and trailing slashes"""
        parsed = urlparse(url)
        normalized = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip('/') or '/',
            parsed.params,
            parsed.query,
            ''
        ))
        return normalized

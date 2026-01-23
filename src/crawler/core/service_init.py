import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Any, Dict, List, Set
from urllib.parse import urlparse, urlunparse

import aiohttp

from src.crawler.models import CrawlConfig
from src.crawler.state.progress_tracker import ProgressTracker
from src.crawler.state.job_state import JobState
from src.crawler.storage.url_tracking_manager import URLTrackingManager
from src.crawler.storage.summary_manager import SummaryManager
from src.crawler.core.service_rate import RateLimiter
from src.crawler.core.sitemap_scraper import DEFAULT_SITEMAP_BASE


class ServiceInitMixin:
    """Initializer and basic setup helpers for CrawlerService."""

    def __init__(
        self,
        config: CrawlConfig,
        job_id: Optional[str] = None,
        communication_service: Optional[Any] = None,
        job_state: Optional[JobState] = None,
        storage_manager: Optional[Any] = None
    ):
        self.config = config
        self.visited_urls: Set[str] = set()
        self.to_visit: List[str] = []
        self.url_depth: Dict[str, int] = {}
        self.url_source: Dict[str, str] = {}
        self.sitemap_lastmod: Dict[str, str] = {}
        self.pages_data: List[Dict] = []
        self.rate_limiter = RateLimiter(config.max_rpm, config.request_delay)
        self.semaphore = asyncio.Semaphore(config.max_concurrency)
        self.page_counter = 0
        self.counter_lock = asyncio.Lock()
        self.allow_over_max_pages = False
        self.abort_crawl = False
        self.abort_reason: Optional[str] = None
        self.abort_lock = asyncio.Lock()
        self.consecutive_5xx = 0
        self.consecutive_5xx_lock = asyncio.Lock()

        self.communication_service = communication_service
        self.job_state = job_state
        self.storage_manager = storage_manager
        self.job_id = job_id

        self.progress_tracker = None
        self.url_tracking_manager = None
        self.summary_manager = None

        base_path = None
        if self.job_id and self.storage_manager:
            base_path = str(self.storage_manager.base_path)
            self.progress_tracker = ProgressTracker(event_emitter=self.communication_service)
            self.url_tracking_manager = URLTrackingManager(job_id=job_id, base_path=base_path)
            self.summary_manager = SummaryManager(job_id=job_id, base_path=base_path)

        self.http_session: Optional[aiohttp.ClientSession] = None

        default_sitemap_path = None
        if self.job_id and self.storage_manager:
            default_sitemap_path = str(self.storage_manager.get_job_directory() / "sitemap.json")
        self.sitemap_path = (
            self.config.sitemap_output
            or os.getenv("SITEMAP_JSON")
            or os.getenv("HAWK_SITEMAP_JSON")
            or default_sitemap_path
        )
        self.sitemap_map = self._load_sitemap_map(self.sitemap_path)
        self.sitemap_base = self.config.sitemap_base or os.getenv("SITEMAP_BASE", DEFAULT_SITEMAP_BASE)
        self.crawl_host = urlparse(str(self.config.url)).hostname

        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }

        if not config.label:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            domain = urlparse(str(config.url)).netloc.replace(".", "_")
            self.config.label = f"{domain}_{timestamp}"

        if self.storage_manager:
            self.output_dir = self.storage_manager.get_job_directory()
        else:
            self.output_dir = Path(config.output_dir) / self.config.label

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

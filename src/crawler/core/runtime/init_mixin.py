import asyncio
import logging
from typing import Optional, Any

import aiohttp

from hawki_crawler.crawler.core.runtime.state import build_crawl_runtime_state
from hawki_crawler.crawler.core.runtime.job_helpers import build_job_helpers
from hawki_crawler.crawler.core.runtime.defaults import (
    default_http_headers,
    resolve_output_directory,
)
from hawki_crawler.crawler.models import CrawlConfig
from hawki_crawler.crawler.policies.url_policy import UrlPolicyService
from hawki_crawler.crawler.state.job_state import JobState
from hawki_crawler.crawler.sitemap.runtime_state import build_sitemap_runtime_state
from hawki_crawler.crawler.storage.runtime_storage import RuntimeStorageService
from hawki_crawler.crawler.profiles import resolve_site_profile


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
        self._init_crawl_runtime_state(config, pause_event)
        self._init_external_services(communication_service, job_state, storage_manager, job_id)
        self._init_job_logger()
        self.site_profile = resolve_site_profile(str(config.url), config.site_profile_path)
        self._init_url_policy()
        self._init_job_helpers(job_id)
        self._init_runtime_clients()
        self._init_sitemap_state()
        self._init_url_policy()
        self._init_http_headers()
        self._init_output_paths(config)
        self._init_runtime_storage()

    def _init_crawl_runtime_state(
        self,
        config: CrawlConfig,
        pause_event: Optional[asyncio.Event],
    ) -> None:
        """Attach mutable crawl state used by execution/runtime mixins."""
        state = build_crawl_runtime_state(config=config, pause_event=pause_event)
        for name, value in vars(state).items():
            setattr(self, name, value)

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
        helpers = build_job_helpers(
            job_id=job_id,
            storage_manager=self.storage_manager,
            site_profile=self.site_profile,
            communication_service=self.communication_service,
            default_logger=self.job_logger,
        )
        self.progress_tracker = helpers.progress_tracker
        self.url_tracking_manager = helpers.url_tracking_manager
        self.summary_manager = helpers.summary_manager
        self.file_event_publisher = helpers.file_event_publisher
        self.job_logger = helpers.job_logger

    def _init_runtime_clients(self) -> None:
        """Clients that are opened lazily and closed after the crawl."""
        self.http_session: Optional[aiohttp.ClientSession] = None

    def _init_url_policy(self) -> None:
        """Inject URL policy decisions as a real service instead of a mixin."""
        self.url_policy = UrlPolicyService(
            site_profile=self.site_profile,
            crawl_host=getattr(self, "crawl_host", None),
        )

    def _init_sitemap_state(self) -> None:
        """Sitemap input and lookup state used by sitemap-related mixins."""
        state = build_sitemap_runtime_state(
            config=self.config,
            job_id=self.job_id,
            storage_manager=self.storage_manager,
            site_profile=self.site_profile,
            load_sitemap_map=self.load_sitemap_map,
            load_sitemap_urls=self.load_sitemap_urls,
        )
        self.sitemap_lastmod = state.sitemap_lastmod
        self.sitemap_path = state.sitemap_path
        self.sitemap_map = state.sitemap_map
        self.sitemap_urls = state.sitemap_urls
        self.sitemap_base = state.sitemap_base
        self.crawl_host = state.crawl_host

    def _init_http_headers(self) -> None:
        """Default request headers used by HTTP and browser fetches."""
        self.headers = default_http_headers()

    def _init_output_paths(self, config: CrawlConfig) -> None:
        """Resolve the label and output directory after job storage is known."""
        self.output_dir = resolve_output_directory(
            config=config,
            storage_manager=self.storage_manager,
        )

    def _init_runtime_storage(self) -> None:
        """Inject output directory creation as a real storage service."""
        self.runtime_storage = RuntimeStorageService(
            storage_manager=self.storage_manager,
            output_dir=self.output_dir,
            skip_images=self.config.skip_images,
        )

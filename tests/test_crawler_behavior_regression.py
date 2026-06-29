import asyncio
import json
import logging
from datetime import datetime
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from crawl4ai.async_configs import CacheMode

from hawki_crawler.app import job_lifecycle
from hawki_crawler.crawler.models import CrawlConfig, CrawlStatus
from hawki_crawler.crawler.assets.asset_policy import AssetPolicy
from hawki_crawler.crawler.assets.asset_saver import AssetSaver
from hawki_crawler.crawler.assets.file_downloader import FileDownloader
from hawki_crawler.crawler.assets.image_downloader import ImageDownloader
from hawki_crawler.crawler.assets.resource_detector import ResourceDetector
from hawki_crawler.crawler.core.execution import execution_mixin as execution_module
from hawki_crawler.crawler.core.execution.execution_mixin import ServiceCrawlExecutionMixin
from hawki_crawler.crawler.core.execution.summary import finalize_crawl_summary
from hawki_crawler.crawler.core.runtime.control import (
    request_browser_restart,
    request_safe_stop,
    update_total_url_counts,
)
from hawki_crawler.crawler.core.runtime.state import build_crawl_runtime_state
from hawki_crawler.crawler.core.runtime.job_helpers import build_job_helpers
from hawki_crawler.crawler.core.runtime.memory_watchdog import (
    read_cgroup_memory_usage_ratio,
    wait_until_memory_relief,
)
from hawki_crawler.crawler.core.runtime.defaults import (
    BROWSER_RESTART_DEFAULTS,
    DEFAULT_HTTP_HEADERS,
    MEMORY_WATCHDOG_DEFAULTS,
    default_http_headers,
    resolve_output_directory,
)
from hawki_crawler.crawler.core.runtime.run_config import build_crawler_run_config
from hawki_crawler.crawler.core.service import CrawlerService
from hawki_crawler.crawler.parsing.content_helpers import clean_html_for_markdown, finalize_markdown_content
from hawki_crawler.crawler.parsing.date_language import DateLanguageService
from hawki_crawler.crawler.policies.url_normalization import normalize_url
from hawki_crawler.crawler.policies.url_policy import UrlPolicyService
from hawki_crawler.crawler.sitemap.sitemap_mixin import ServiceSitemapMixin
from hawki_crawler.crawler.sitemap.runtime_state import build_sitemap_runtime_state
from hawki_crawler.crawler.sitemap.scraper import SitemapScraper
from hawki_crawler.crawler.sitemap.service import SitemapService
from hawki_crawler.crawler.storage.page_output import build_page_metadata, determine_content_status
from hawki_crawler.crawler.storage.runtime_directories import (
    create_runtime_page_directory,
    setup_output_directory,
)
from hawki_crawler.crawler.storage.runtime_storage import RuntimeStorageService
from hawki_crawler.crawler.storage.storage_manager import StorageManager
from hawki_crawler.common.logging_setup import configure_job_file_logger


class _PolicyAndSitemapService(ServiceSitemapMixin):
    def __init__(self, *, site_profile=None, crawl_host="example.com") -> None:
        self.site_profile = site_profile or {}
        self.crawl_host = crawl_host
        self.url_policy = UrlPolicyService(site_profile=self.site_profile, crawl_host=self.crawl_host)
        self.sitemap_map = {}
        self.sitemap_lastmod = {}
        self.url_tracking_manager = None
        self.headers = {}


class _FakeAsyncWebCrawler:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class _FreshRescrapeService(ServiceCrawlExecutionMixin):
    def __init__(self) -> None:
        self.config = CrawlConfig(
            job_id="fresh-rescrape",
            url="https://example.com",
            max_pages=1,
            rescrape_failed=True,
        )
        self.job_id = "fresh-rescrape"
        self.job_logger = logging.getLogger("test.fresh_rescrape")
        self.http_session = None
        self.url_tracking_manager = self.FakeUrlTrackingManager()
        self.job_state = self.FakeJobState()
        self.progress_tracker = None
        self.progress_publisher = self.FakeProgressPublisher()
        self.summary_manager = None
        self.output_dir = "/tmp/fresh-rescrape"
        self.headers = {}
        self.url_policy = UrlPolicyService(crawl_host="example.com")
        self.visited_urls = set()
        self.to_visit = []
        self.url_depth = {}
        self.url_source = {}
        self.page_counter = 0
        self.abort_crawl = False
        self.abort_reason = None
        self.restart_crawler = False
        self.restart_urls = []
        self.restart_lock = asyncio.Lock()
        self.browser_restart_count = 0
        self.enable_browser_restarts = False
        self.max_browser_restarts = 0
        self.restart_reason = None
        self.captured_to_visit = []

    class FakeUrlTrackingManager:
        def __init__(self) -> None:
            self.added = []

        async def initialize(self) -> None:
            pass

        async def purge_forbidden_hosts(self, forbidden_hosts) -> int:
            return 0

        async def get_all_urls(self):
            return {}

        async def add_url(self, url: str, *, source: str, sitemap_date=None) -> None:
            self.added.append((url, source, sitemap_date))

    class FakeJobState:
        def __init__(self) -> None:
            self.total_urls = []

        async def set_status(self, status: str) -> None:
            pass

        async def set_total_urls(self, total: int) -> None:
            self.total_urls.append(total)

        async def get_snapshot(self):
            return SimpleNamespace(completed_urls=0, failed_urls=0)

        async def set_error(self, error: str) -> None:
            pass

    class FakeProgressPublisher:
        async def send_stage(self, *args, **kwargs) -> None:
            pass

        async def send_summary(self, *args, **kwargs) -> None:
            pass

    async def run_sitemap_scrape(self) -> None:
        pass

    async def setup_directories(self) -> None:
        pass

    async def is_sitemap(self, url: str) -> bool:
        return False

    def lookup_sitemap_entry(self, url: str):
        return None

    def get_sitemap_date(self, sitemap_entry) -> None:
        return None

    async def _run_crawl_batches(self, crawler) -> None:
        self.captured_to_visit = list(self.to_visit)
        self.to_visit = []


def test_url_policy_blocks_forbidden_hosts_patterns_and_contact_forms(tmp_path) -> None:
    rules_file = tmp_path / "forbidden_urls.txt"
    rules_file.write_text("blocked.example\n/private\n", encoding="utf-8")
    service = UrlPolicyService(
        site_profile={
            "forbidden": {
                "rules_file": str(rules_file),
                "hosts": ["profile-blocked.example"],
                "url_patterns": ["tracking"],
            }
        }
    )

    assert service.is_forbidden_url("https://blocked.example/page") is True
    assert service.is_forbidden_url("https://sub.profile-blocked.example/page") is True
    assert service.is_forbidden_url("https://example.com/private/page") is True
    assert service.is_forbidden_url("https://example.com/page?utm=tracking") is True
    assert service.is_forbidden_url("https://example.com/de/form/contact?form_type=person&entity_key=1") is True
    assert service.is_forbidden_url("https://example.com/public") is False


def test_url_policy_allows_only_configured_discovery_hosts() -> None:
    service = UrlPolicyService(
        site_profile={"discovery": {"allowed_hosts": ["example.com", "docs.example.org"]}},
        crawl_host="fallback.example",
    )

    assert service.is_discovery_url_allowed("https://example.com/page") is True
    assert service.is_discovery_url_allowed("https://sub.docs.example.org/page") is True
    assert service.is_discovery_url_allowed("https://fallback.example/page") is False
    assert service.is_discovery_url_allowed("mailto:team@example.com") is False


def test_url_normalization_removes_fragments_and_trailing_slashes() -> None:
    assert normalize_url("https://example.com/path/#section") == "https://example.com/path"
    assert normalize_url("https://example.com/path/?a=1#section") == "https://example.com/path?a=1"
    assert normalize_url("https://example.com/") == "https://example.com/"
    assert normalize_url("https://example.com") == "https://example.com/"


@pytest.mark.asyncio
async def test_fresh_rescrape_failed_job_still_seeds_start_url(monkeypatch) -> None:
    monkeypatch.setattr(execution_module, "AsyncWebCrawler", _FakeAsyncWebCrawler)
    service = _FreshRescrapeService()

    await service.crawl()

    assert service.captured_to_visit == ["https://example.com/"]
    assert service.url_tracking_manager.added == [("https://example.com/", "seed", None)]
    assert service.job_state.total_urls == [1]


def test_sitemap_json_loading_normalizes_metadata_and_filters_forbidden_urls(tmp_path) -> None:
    sitemap_file = tmp_path / "sitemap.json"
    sitemap_file.write_text(
        json.dumps(
            {
                "https://www.example.com/page/": {"lastmod": "2026-01-01", "language": "de"},
                "https://blocked.example/private": "2026-01-02",
            }
        ),
        encoding="utf-8",
    )
    url_policy = UrlPolicyService(
        site_profile={"forbidden": {"hosts": ["blocked.example"]}},
    )
    service = SitemapService(is_forbidden_url=url_policy.is_forbidden_url)

    sitemap_map = service.load_sitemap_map(str(sitemap_file))
    sitemap_urls = service.load_sitemap_urls(str(sitemap_file))

    assert sitemap_map["example.com/page"]["last_modified"] == "2026-01-01"
    assert sitemap_map["example.com/page"]["language"] == "de"
    assert sitemap_map["blocked.example/private"]["last_modified"] == "2026-01-02"
    assert sitemap_urls == ["https://www.example.com/page/"]


def test_date_language_service_extracts_dates_from_meta_and_time_tags() -> None:
    service = DateLanguageService()
    html = """
    <html>
      <head>
        <meta property="article:published_time" content="Wed, 20 May 2026 10:00:00 GMT">
      </head>
      <body>
        <time datetime="Thu, 21 May 2026 12:30:00 GMT">21 May 2026</time>
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")

    dates = service.extract_dates(html, soup)

    assert dates == {
        "published_at": "2026-05-20T10:00:00+00:00",
        "updated_at": "2026-05-21T12:30:00+00:00",
    }


def test_date_language_service_detects_language_by_precedence() -> None:
    service = DateLanguageService(
        sitemap_lookup=lambda url: {"language": "de"} if url == "https://example.com/from-sitemap" else None
    )

    assert service.detect_language(None, {"content-language": "en-US,en;q=0.8"}, url="https://example.com/from-sitemap") == "DE"
    assert service.detect_language(None, {"content-language": "en-US,en;q=0.8"}) == "EN-US"
    assert service.detect_language("<html lang='fr-FR'></html>", None) == "FR"
    assert service.detect_language(
        "<html><meta http-equiv='Content-Language' content='es-MX,es'></html>",
        None,
    ) == "ES-MX"
    assert service.detect_language("<html></html>", None) is None


@pytest.mark.asyncio
async def test_discover_urls_normalizes_deduplicates_and_applies_policy() -> None:
    service = _PolicyAndSitemapService(
        site_profile={"discovery": {"allowed_hosts": ["example.com"]}},
        crawl_host="example.com",
    )
    html = """
    <a href="/one#section">One</a>
    <a href="https://example.com/one">Duplicate</a>
    <a href="https://other.example/two">Other</a>
    <a href="mailto:team@example.com">Mail</a>
    """

    urls = await service.discover_urls(html, "https://example.com/start")

    assert urls == ["https://example.com/one"]


def test_page_metadata_content_status_and_asset_counts_are_stable() -> None:
    assert determine_content_status("Body text") == "success"
    assert determine_content_status("Body text", quality_classification="noisy") == "noisy"
    assert determine_content_status("", low_quality_content="Some extracted text") == "partial"
    assert determine_content_status("", has_binary_assets=True) == "binary"
    assert determine_content_status("") == "empty"

    metadata = build_page_metadata(
        url="HTTPS://Example.com/Page/",
        source_url="https://example.com/source/",
        canonical_url="https://example.com/page/",
        url_hash="abc12345",
        title=" Example Page ",
        lang="DE",
        fetched_at="2026-05-21T12:00:00Z",
        tags=[" research ", None, "None", "crawler"],
        images=[
            {"url": "https://example.com/img.png", "filename": "img.png"},
            {"url": "https://example.com/img.png", "filename": "duplicate.png"},
        ],
        pdfs=[{"url": "https://example.com/file.pdf", "filename": "file.pdf"}],
        http_status=200,
        quality={"score": 88, "quality_label": "high", "content_classification": "success"},
        markdown="Some useful page content",
        source_type="sitemap",
        depth=2,
    )

    assert metadata["url"] == "https://example.com/Page"
    assert metadata["source_url"] == "https://example.com/source"
    assert metadata["status"]["content_status"] == "success"
    assert metadata["status"]["word_count"] == 4
    assert metadata["source"] == {"type": "sitemap", "depth": 2}
    assert metadata["tags"] == ["research", "crawler"]
    assert len(metadata["images"]) == 1
    assert len(metadata["documents"]["pdfs"]) == 1


def test_content_helpers_select_main_content_and_cleanup_markdown() -> None:
    html = """
    <html>
      <body>
        <nav>Cookie settings Share this page</nav>
        <article>
          <h1>Research Update</h1>
          <p>This paragraph contains enough meaningful words to be selected as the main content.</p>
          <p>Another paragraph keeps the article richer than the surrounding navigation.</p>
        </article>
        <footer>Contact us Back to top</footer>
      </body>
    </html>
    """

    selection = clean_html_for_markdown(html, site_noise_phrases=["cookie settings"])
    markdown, warnings = finalize_markdown_content(
        "# Research Update\n# Research Update\n- thin\nUseful sentence with enough words.\nCookie settings",
        site_noise_phrases=["cookie settings"],
    )

    assert "Research Update" in selection["text"]
    assert "Cookie settings" not in selection["text"]
    assert selection["candidate_details"]
    assert markdown == "# Research Update\nUseful sentence with enough words."
    assert "removed_duplicate_heading" in warnings
    assert "removed_markdown_noise_line" in warnings


def test_job_file_logger_writes_job_context_once(tmp_path) -> None:
    job_id = "regression_logger_job"
    log_path = tmp_path / "crawler.log"
    logger = logging.getLogger(f"crawler.{job_id}")
    handler_name = f"job_error_file_{job_id}"

    for handler in list(logger.handlers):
        if getattr(handler, "name", "") == handler_name:
            logger.removeHandler(handler)
            handler.close()

    try:
        first_adapter = configure_job_file_logger(job_id, log_path)
        second_adapter = configure_job_file_logger(job_id, log_path)

        first_adapter.info("crawl started")
        second_adapter.info("crawl continued")

        matching_handlers = [
            handler for handler in logger.handlers if getattr(handler, "name", "") == handler_name
        ]
        assert len(matching_handlers) == 1

        log_text = log_path.read_text(encoding="utf-8")
        assert "crawl started [job_id=regression_logger_job]" in log_text
        assert "crawl continued [job_id=regression_logger_job]" in log_text
    finally:
        for handler in list(logger.handlers):
            if getattr(handler, "name", "") == handler_name:
                logger.removeHandler(handler)
                handler.close()


def test_job_helpers_factory_wires_persistent_job_services(tmp_path) -> None:
    job_id = "job_helpers_regression"
    storage_manager = StorageManager(job_id=job_id, base_path=str(tmp_path))
    default_logger = logging.LoggerAdapter(logging.getLogger("crawler"), {"job_id": "unknown"})
    logger = logging.getLogger(f"crawler.{job_id}")
    handler_name = f"job_error_file_{job_id}"

    for handler in list(logger.handlers):
        if getattr(handler, "name", "") == handler_name:
            logger.removeHandler(handler)
            handler.close()

    try:
        fallback_helpers = build_job_helpers(
            job_id=None,
            storage_manager=None,
            site_profile={},
            default_logger=default_logger,
        )
        helpers = build_job_helpers(
            job_id=job_id,
            storage_manager=storage_manager,
            site_profile={"forbidden": {"hosts": ["blocked.example"]}},
            default_logger=default_logger,
        )

        assert fallback_helpers.job_logger is default_logger
        assert fallback_helpers.progress_tracker is None
        assert helpers.progress_tracker is not None
        assert helpers.url_tracking_manager is not None
        assert helpers.summary_manager is not None
        assert storage_manager.get_job_directory().is_dir()

        helpers.job_logger.warning("helper ready")
        log_text = (storage_manager.get_job_directory() / "crawler.log").read_text(encoding="utf-8")
        assert "helper ready [job_id=job_helpers_regression]" in log_text
    finally:
        for handler in list(logger.handlers):
            if getattr(handler, "name", "") == handler_name:
                logger.removeHandler(handler)
                handler.close()


@pytest.mark.asyncio
async def test_finalize_crawl_summary_stops_saves_publishes_and_logs(tmp_path) -> None:
    class FakeProgressTracker:
        def __init__(self) -> None:
            self.stopped = False

        async def stop(self) -> None:
            self.stopped = True

        async def get_summary(self):
            return {
                "started_at": "2026-05-21T10:00:00Z",
                "completed_at": "2026-05-21T10:00:05Z",
                "duration_seconds": 5,
                "total_urls": 3,
                "completed_urls": 2,
                "failed_urls": 1,
                "processing_urls": 0,
                "success_rate": 66.67,
                "stats": {"requests": 3},
            }

    class FakeSummaryManager:
        def __init__(self) -> None:
            self.saved = []

        async def save_summary(self, summary) -> None:
            self.saved.append(summary)

    class FakeLogger:
        def __init__(self) -> None:
            self.messages = []

        def info(self, message, *args) -> None:
            self.messages.append(message % args if args else message)

    progress_tracker = FakeProgressTracker()
    summary_manager = FakeSummaryManager()
    logger = FakeLogger()
    sent_summaries = []

    async def send_summary(summary) -> None:
        sent_summaries.append(summary)

    summary = await finalize_crawl_summary(
        progress_tracker=progress_tracker,
        summary_manager=summary_manager,
        send_summary=send_summary,
        job_logger=logger,
        job_id="summary-job",
        stage="failed",
        output_directory=tmp_path,
        error="crawl failed",
    )

    assert progress_tracker.stopped is True
    assert summary_manager.saved == [summary]
    assert sent_summaries == [summary]
    assert summary["job_id"] == "summary-job"
    assert summary["status"] == "failed"
    assert summary["output_directory"] == str(tmp_path)
    assert summary["error"] == "crawl failed"
    assert logger.messages


def test_runtime_defaults_preserve_headers_limits_and_output_paths(tmp_path) -> None:
    headers = default_http_headers()
    headers["User-Agent"] = "changed"

    assert DEFAULT_HTTP_HEADERS["User-Agent"].startswith("Mozilla/5.0")
    assert BROWSER_RESTART_DEFAULTS.max_restarts == 3
    assert BROWSER_RESTART_DEFAULTS.interval_seconds == 3600
    assert BROWSER_RESTART_DEFAULTS.enabled is False
    assert MEMORY_WATCHDOG_DEFAULTS.enabled is True
    assert MEMORY_WATCHDOG_DEFAULTS.restart_threshold == 0.9
    assert MEMORY_WATCHDOG_DEFAULTS.resume_threshold == 0.1
    assert MEMORY_WATCHDOG_DEFAULTS.restart_wait_seconds == 300

    config = SimpleNamespace(
        url="https://example.edu/path",
        output_dir=str(tmp_path / "output"),
        label=None,
    )
    output_dir = resolve_output_directory(
        config=config,
        storage_manager=None,
        now=datetime(2026, 5, 21, 12, 30, 0),
    )

    assert config.label == "example_edu_20260521_123000"
    assert output_dir == tmp_path / "output" / "example_edu_20260521_123000"

    storage_manager = StorageManager(job_id="runtime_defaults_job", base_path=str(tmp_path))
    stored_config = SimpleNamespace(
        url="https://example.edu/path",
        output_dir=str(tmp_path / "ignored"),
        label=None,
    )
    stored_output_dir = resolve_output_directory(
        config=stored_config,
        storage_manager=storage_manager,
        now=datetime(2026, 5, 21, 12, 30, 0),
    )

    assert stored_config.label == "example_edu_20260521_123000"
    assert stored_output_dir == storage_manager.get_job_directory()


def test_sitemap_runtime_state_resolves_paths_base_and_loads(monkeypatch, tmp_path) -> None:
    site_sitemap = tmp_path / "site_sitemap.json"
    fallback_sitemap = tmp_path / "fallback_sitemap.json"
    monkeypatch.setenv("SITE_SITEMAP_JSON", str(site_sitemap))
    monkeypatch.setenv("SITEMAP_JSON", str(fallback_sitemap))
    monkeypatch.setenv("SITEMAP_BASE", "https://env.example/sitemap.xml")
    calls = []

    def load_sitemap_map(path):
        calls.append(("map", path))
        return {"example.edu/page": {"last_modified": "2026-05-21"}}

    def load_sitemap_urls(path):
        calls.append(("urls", path))
        return ["https://example.edu/page"]

    state = build_sitemap_runtime_state(
        config=SimpleNamespace(
            url="https://www.example.edu/start",
            sitemap_output=None,
            sitemap_base=None,
        ),
        job_id="job-1",
        storage_manager=StorageManager(job_id="job-1", base_path=str(tmp_path)),
        site_profile={"sitemap": {"base_url": "https://profile.example/sitemap.xml"}},
        load_sitemap_map=load_sitemap_map,
        load_sitemap_urls=load_sitemap_urls,
    )

    assert state.sitemap_lastmod == {}
    assert state.sitemap_path == str(site_sitemap)
    assert state.sitemap_map == {"example.edu/page": {"last_modified": "2026-05-21"}}
    assert state.sitemap_urls == ["https://example.edu/page"]
    assert state.sitemap_base == "https://env.example/sitemap.xml"
    assert state.crawl_host == "www.example.edu"
    assert calls == [("map", str(site_sitemap)), ("urls", str(site_sitemap))]

    explicit_state = build_sitemap_runtime_state(
        config=SimpleNamespace(
            url="https://example.edu/start",
            sitemap_output="/tmp/explicit-sitemap.json",
            sitemap_base="https://explicit.example/sitemap.xml",
        ),
        job_id=None,
        storage_manager=None,
        site_profile={},
        load_sitemap_map=lambda path: {"path": {"value": path}},
        load_sitemap_urls=lambda path: [path],
    )

    assert explicit_state.sitemap_path == "/tmp/explicit-sitemap.json"
    assert explicit_state.sitemap_base == "https://explicit.example/sitemap.xml"
    assert explicit_state.sitemap_map == {"path": {"value": "/tmp/explicit-sitemap.json"}}
    assert explicit_state.sitemap_urls == ["/tmp/explicit-sitemap.json"]


def test_sitemap_scraper_page_url_preserves_existing_query_params() -> None:
    scraper = SitemapScraper(
        base_url="https://www.uni-hildesheim.de/sitemap.xml?sitemap=pages&cHash=abc123&page=9",
        output_path="/tmp/site_sitemap.json",
    )

    assert (
        scraper._build_page_url(2)
        == "https://www.uni-hildesheim.de/sitemap.xml?page=2&sitemap=pages&cHash=abc123"
    )


def test_crawl_runtime_state_preserves_mutable_defaults() -> None:
    pause_event = asyncio.Event()
    state = build_crawl_runtime_state(
        config=SimpleNamespace(max_rpm=120, request_delay=250, max_concurrency=4),
        pause_event=pause_event,
        browser_last_restart=123.5,
    )

    assert state.visited_urls == set()
    assert state.to_visit == []
    assert state.url_depth == {}
    assert state.url_source == {}
    assert state.pages_data == []
    assert state.rate_limiter.max_rpm == 120
    assert state.rate_limiter.request_delay == 0.25
    assert state.semaphore._value == 4
    assert state.page_counter == 0
    assert state.allow_over_max_pages is False
    assert state.consecutive_5xx == 0
    assert state.abort_crawl is False
    assert state.abort_reason is None
    assert state.pause_event is pause_event
    assert state.pause_logged is False
    assert state.restart_crawler is False
    assert state.restart_urls == []
    assert state.browser_restart_count == 0
    assert state.max_browser_restarts == 3
    assert state.browser_restart_interval_seconds == 3600
    assert state.browser_last_restart == 123.5
    assert state.enable_browser_restarts is False
    assert state.restart_reason is None
    assert state.enable_memory_watchdog is True
    assert state.memory_restart_threshold == 0.9
    assert state.memory_resume_threshold == 0.1
    assert state.memory_restart_wait_seconds == 300
    assert isinstance(state.counter_lock, asyncio.Lock)
    assert isinstance(state.consecutive_5xx_lock, asyncio.Lock)
    assert isinstance(state.abort_lock, asyncio.Lock)
    assert isinstance(state.restart_lock, asyncio.Lock)


def test_crawler_run_config_preserves_runtime_defaults() -> None:
    config = CrawlConfig(
        job_id="run-config-job",
        url="https://example.com",
        wait_until="networkidle",
        page_timeout_ms=12345,
    )

    run_config = build_crawler_run_config(config)

    assert run_config.word_count_threshold == 0
    assert run_config.exclude_external_links is False
    assert run_config.process_iframes is False
    assert run_config.remove_overlay_elements is True
    assert run_config.cache_mode == CacheMode.BYPASS
    assert run_config.wait_until == "networkidle"
    assert run_config.page_timeout == 12345
    assert run_config.delay_before_return_html == 5.0
    assert callable(run_config.fallback_fetch_function)


def test_service_applies_profile_runtime_defaults_when_request_omits_them(tmp_path) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps({"wait_until": "networkidle", "page_timeout_ms": 12345}),
        encoding="utf-8",
    )

    service = CrawlerService(
        CrawlConfig(
            job_id="profile-runtime-defaults",
            url="https://example.com",
            site_profile_path=str(profile_path),
        )
    )

    assert service.config.wait_until == "networkidle"
    assert service.config.page_timeout_ms == 12345


def test_request_runtime_config_overrides_profile_defaults(tmp_path) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps({"wait_until": "networkidle", "page_timeout_ms": 12345}),
        encoding="utf-8",
    )

    service = CrawlerService(
        CrawlConfig(
            job_id="request-runtime-defaults",
            url="https://example.com",
            site_profile_path=str(profile_path),
            wait_until="domcontentloaded",
            page_timeout_ms=5000,
        )
    )

    assert service.config.wait_until == "domcontentloaded"
    assert service.config.page_timeout_ms == 5000


@pytest.mark.asyncio
async def test_crawl_control_helpers_stop_restart_and_update_counts() -> None:
    aborted = False
    abort_reason = None
    pending_urls = ["https://example.com/one", "https://example.com/two"]

    def mark_aborted(reason: str) -> None:
        nonlocal aborted, abort_reason
        aborted = True
        abort_reason = reason

    await request_safe_stop(
        abort_lock=asyncio.Lock(),
        is_aborted=lambda: aborted,
        mark_aborted=mark_aborted,
        pending_urls=pending_urls,
        reason="too many server errors",
    )

    assert aborted is True
    assert abort_reason == "too many server errors"
    assert pending_urls == []

    restart_requested = False
    restart_reason = None
    restart_urls = []

    def mark_restart_requested(reason: str) -> None:
        nonlocal restart_requested, restart_reason
        restart_requested = True
        restart_reason = reason

    await request_browser_restart(
        enabled=True,
        restart_lock=asyncio.Lock(),
        restart_urls=restart_urls,
        mark_restart_requested=mark_restart_requested,
        url="https://example.com/retry",
    )
    await request_browser_restart(
        enabled=True,
        restart_lock=asyncio.Lock(),
        restart_urls=restart_urls,
        mark_restart_requested=mark_restart_requested,
        url="https://example.com/retry",
    )

    assert restart_requested is True
    assert restart_reason == "browser_closed"
    assert restart_urls == ["https://example.com/retry"]

    class FakeJobState:
        def __init__(self) -> None:
            self.updated_totals = []

        async def get_snapshot(self):
            return SimpleNamespace(total_urls=2)

        async def set_total_urls(self, total: int) -> None:
            self.updated_totals.append(total)

    class FakeProgressTracker:
        def __init__(self) -> None:
            self.updated_totals = []

        async def get_progress(self):
            return {"total_urls": 2}

        async def set_total_urls(self, total: int) -> None:
            self.updated_totals.append(total)

    job_state = FakeJobState()
    progress_tracker = FakeProgressTracker()

    await update_total_url_counts(
        new_total=5,
        job_state=job_state,
        progress_tracker=progress_tracker,
    )

    assert job_state.updated_totals == [5]
    assert progress_tracker.updated_totals == [5]


def test_memory_watchdog_reads_cgroup_usage_ratio(tmp_path) -> None:
    current_path = tmp_path / "memory.current"
    limit_path = tmp_path / "memory.max"
    current_path.write_text("25", encoding="utf-8")
    limit_path.write_text("100", encoding="utf-8")

    assert read_cgroup_memory_usage_ratio(paths=[(current_path, limit_path)]) == 0.25

    limit_path.write_text("max", encoding="utf-8")

    assert read_cgroup_memory_usage_ratio(paths=[(current_path, limit_path)]) is None


@pytest.mark.asyncio
async def test_memory_watchdog_waits_until_usage_drops() -> None:
    ratios = iter([0.95, 0.25])
    sleep_calls = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    await wait_until_memory_relief(
        enable_memory_watchdog=True,
        memory_resume_threshold=0.5,
        memory_restart_wait_seconds=30,
        get_memory_usage_ratio=lambda: next(ratios),
        job_logger=logging.getLogger("test.memory_watchdog"),
        sleep=fake_sleep,
        monotonic=lambda: 0,
    )

    assert sleep_calls == [5]


@pytest.mark.asyncio
async def test_runtime_directories_delegate_or_create_legacy_paths(tmp_path) -> None:
    class FakeStorageManager:
        def __init__(self) -> None:
            self.ensured = False
            self.calls = []
            self.page_dir = tmp_path / "managed_page"

        def ensure_job_directory(self) -> None:
            self.ensured = True

        def create_page_directory(
            self,
            page_number: int,
            *,
            create_images_dir: bool,
            create_files_dir: bool,
        ):
            self.calls.append((page_number, create_images_dir, create_files_dir))
            return self.page_dir

    manager = FakeStorageManager()
    await setup_output_directory(storage_manager=manager, output_dir=tmp_path / "ignored")
    managed_page_dir = await create_runtime_page_directory(
        storage_manager=manager,
        output_dir=tmp_path / "ignored",
        page_number=3,
        skip_images=True,
        create_files_dir=True,
    )

    assert manager.ensured is True
    assert manager.calls == [(3, False, True)]
    assert managed_page_dir == manager.page_dir

    legacy_output_dir = tmp_path / "legacy"
    await setup_output_directory(storage_manager=None, output_dir=legacy_output_dir)
    legacy_page_dir = await create_runtime_page_directory(
        storage_manager=None,
        output_dir=legacy_output_dir,
        page_number=7,
        skip_images=False,
        create_files_dir=True,
    )
    no_image_page_dir = await create_runtime_page_directory(
        storage_manager=None,
        output_dir=legacy_output_dir,
        page_number=8,
        skip_images=True,
        create_files_dir=False,
    )

    assert legacy_page_dir == legacy_output_dir / "page_00007"
    assert (legacy_page_dir / "images").is_dir()
    assert (legacy_page_dir / "files").is_dir()
    assert no_image_page_dir == legacy_output_dir / "page_00008"
    assert not (no_image_page_dir / "images").exists()
    assert not (no_image_page_dir / "files").exists()

    service_output_dir = tmp_path / "service_legacy"
    service = RuntimeStorageService(
        storage_manager=None,
        output_dir=service_output_dir,
        skip_images=False,
    )
    await service.setup_directories()
    service_page_dir = await service.create_page_directory(9, create_files_dir=True)

    assert service_page_dir == service_output_dir / "page_00009"
    assert (service_page_dir / "images").is_dir()
    assert (service_page_dir / "files").is_dir()


def test_asset_policy_classifies_links_and_filenames_without_network() -> None:
    policy = AssetPolicy()
    html = """
    <a href="/files/report.pdf?download=1">Report</a>
    <a href="/files/data.csv">Data</a>
    <a href="/files/app.exe">Executable</a>
    <a href="/page">Page</a>
    """

    assert policy.extract_pdf_links(html, "https://example.com/base/") == [
        "https://example.com/files/report.pdf?download=1",
    ]
    assert policy.extract_file_links(html, "https://example.com/base/") == [
        "https://example.com/files/data.csv",
    ]
    assert policy.looks_like_file_url("https://example.com/media/12345") is True
    assert policy.looks_like_file_url("https://example.com/page") is False
    assert policy.is_pdf_resource("https://example.com/download", {"content-type": "application/pdf"}) is True
    assert policy.is_file_resource(
        "https://example.com/download",
        {"content-type": "application/octet-stream"},
    ) is True
    assert policy.is_file_resource(
        "https://example.com/page",
        {"content-type": "text/html; charset=utf-8"},
    ) is False
    assert policy.should_skip_file_download(
        "https://example.com/app.exe",
        "app.exe",
        "application/x-msdownload",
    ) is True
    assert policy.pdf_filename_from_url("https://example.com/März Bericht.pdf") == "Maerz_Bericht.pdf"
    assert policy.file_filename_from_response(
        "https://example.com/download",
        "text/csv",
        "attachment; filename=fächer liste.csv",
    ) == "faecher_liste.csv"


@pytest.mark.asyncio
async def test_asset_saver_writes_fallback_file_and_marks_incomplete(tmp_path) -> None:
    async def create_page_directory(page_number: int, create_files_dir: bool = False):
        page_dir = tmp_path / f"page_{page_number:05d}"
        page_dir.mkdir(parents=True, exist_ok=True)
        if create_files_dir:
            (page_dir / "files").mkdir(parents=True, exist_ok=True)
        return page_dir

    saver = AssetSaver(
        storage_manager=None,
        create_page_directory=create_page_directory,
        skip_images=True,
    )

    result = await saver.save_file_bytes(
        file_url="https://example.com/files/report.pdf",
        filename="report.pdf",
        file_bytes=b"pdf-bytes",
        page_number=2,
        content_type="application/pdf",
        incomplete=True,
        error=RuntimeError("partial content"),
    )

    saved_path = tmp_path / "page_00002" / "files" / "report.pdf"
    assert saved_path.read_bytes() == b"pdf-bytes"
    assert result["local_path"] == str(saved_path.resolve())
    assert result["relative_path"] == "files/report.pdf"
    assert result["incomplete"] is True
    assert result["error"] == "partial content"


@pytest.mark.asyncio
async def test_image_downloader_saves_supported_image_without_network(tmp_path) -> None:
    class FakeRateLimiter:
        def __init__(self) -> None:
            self.calls = 0

        async def acquire(self) -> None:
            self.calls += 1

    class FakeImageResponse:
        status = 200
        headers = {"Content-Type": "image/png; charset=binary"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def read(self) -> bytes:
            return b"image-bytes"

    class FakeSession:
        def __init__(self) -> None:
            self.requested = []

        def get(self, url, **kwargs):
            self.requested.append((url, kwargs))
            return FakeImageResponse()

    images_dir = tmp_path / "images"
    images_dir.mkdir()
    rate_limiter = FakeRateLimiter()
    session = FakeSession()
    downloader = ImageDownloader(rate_limiter=rate_limiter)

    filename = await downloader.download_image(
        "https://example.com/assets/logo.png",
        session,
        images_dir,
    )

    assert filename == "logo.png"
    assert (images_dir / "logo.png").read_bytes() == b"image-bytes"
    assert rate_limiter.calls == 1
    assert session.requested[0][0] == "https://example.com/assets/logo.png"


@pytest.mark.asyncio
async def test_resource_detector_fetches_and_classifies_head_resources() -> None:
    class FakeRateLimiter:
        def __init__(self) -> None:
            self.calls = 0

        async def acquire(self) -> None:
            self.calls += 1

    class FakeHeadResponse:
        status = 200
        headers = {"Content-Type": "Application/PDF", "X-Test": "yes"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class FakeHeadSession:
        def __init__(self) -> None:
            self.requested = []

        def head(self, url, **kwargs):
            self.requested.append((url, kwargs))
            return FakeHeadResponse()

    async def fake_fetch_head(_url):
        return 200, {"content-type": "application/octet-stream"}

    rate_limiter = FakeRateLimiter()
    session = FakeHeadSession()
    detector = ResourceDetector(
        rate_limiter=rate_limiter,
        http_session=session,
        logger=logging.getLogger("test.resource_detector"),
    )
    detector_with_override = ResourceDetector(
        rate_limiter=rate_limiter,
        http_session=None,
        logger=logging.getLogger("test.resource_detector"),
        fetch_head=fake_fetch_head,
    )

    status, headers = await detector.fetch_head("https://example.com/report")

    assert status == 200
    assert headers["content-type"] == "Application/PDF"
    assert headers["x-test"] == "yes"
    assert rate_limiter.calls == 1
    assert await detector.is_pdf_resource("https://example.com/report", head_headers=headers) is True
    assert await detector_with_override.is_file_resource("https://example.com/download") is True


@pytest.mark.asyncio
async def test_file_downloader_saves_pdf_without_network() -> None:
    class FakeRateLimiter:
        def __init__(self) -> None:
            self.calls = 0

        async def acquire(self) -> None:
            self.calls += 1

    class FakeAssetSaver:
        def __init__(self) -> None:
            self.calls = []

        async def save_file_bytes(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "url": kwargs["file_url"],
                "local_path": "/tmp/report.pdf",
                "relative_path": "files/report.pdf",
                "filename": kwargs["filename"],
                "content_type": kwargs["content_type"],
            }

    class FakeStream:
        async def iter_chunked(self, _size):
            yield b"pdf-bytes"

    class FakeResponse:
        status = 200
        headers = {"Content-Type": "application/pdf"}
        content = FakeStream()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class FakeSession:
        def __init__(self) -> None:
            self.requested = []

        def get(self, url, **kwargs):
            self.requested.append((url, kwargs))
            return FakeResponse()

    rate_limiter = FakeRateLimiter()
    saver = FakeAssetSaver()
    session = FakeSession()
    downloader = FileDownloader(
        rate_limiter=rate_limiter,
        headers={"User-Agent": "test"},
        asset_saver=saver,
        logger=logging.getLogger("test.file_downloader"),
    )

    result = await downloader.fetch_and_save_pdf(
        "https://example.com/files/report.pdf",
        page_number=3,
        session=session,
        page_url="https://example.com/page",
    )

    assert result["filename"] == "report.pdf"
    assert rate_limiter.calls == 1
    assert saver.calls[0]["file_bytes"] == b"pdf-bytes"
    assert saver.calls[0]["page_number"] == 3


@pytest.mark.asyncio
async def test_completed_url_manifest_upserts_records_by_url(tmp_path) -> None:
    manager = StorageManager("job-1", base_path=str(tmp_path))
    manager.ensure_job_directory()
    url_hash = "a" * 64
    manager.create_hash_directory(url_hash)

    first = build_page_metadata(
        url="https://example.com/page",
        url_hash=url_hash,
        title="Old title",
        fetched_at="2026-05-21T10:00:00Z",
        http_status=200,
        quality={"score": 90, "quality_label": "high", "content_classification": "success"},
        markdown="old content",
        source_type="seed",
    )
    second = build_page_metadata(
        url="https://example.com/page",
        url_hash=url_hash,
        title="New title",
        fetched_at="2026-05-21T11:00:00Z",
        http_status=200,
        quality={"score": 70, "quality_label": "medium", "content_classification": "success"},
        markdown="new content",
        source_type="sitemap",
    )

    await manager.upsert_completed_url_record(first, url_hash=url_hash)
    await manager.upsert_completed_url_record(second, url_hash=url_hash)

    manifest = json.loads(manager.get_completed_urls_manifest_path().read_text(encoding="utf-8"))
    assert manifest["job_id"] == "job-1"
    assert manifest["total_completed"] == 1
    assert len(manifest["records"]) == 1
    record = manifest["records"][0]
    assert record["url"] == "https://example.com/page"
    assert record["title"] == "New title"
    assert record["source_type"] == "sitemap"
    assert record["content_path"].endswith("/content.md")
    assert record["metadata_path"].endswith("/data.json")


@pytest.mark.asyncio
async def test_storage_manager_saves_hash_and_legacy_assets_to_expected_paths(tmp_path) -> None:
    manager = StorageManager("job-1", base_path=str(tmp_path))
    manager.ensure_job_directory()
    url_hash = "b" * 64
    manager.create_hash_directory(url_hash)
    manager.create_page_directory(3)

    assert await manager.save_hash_image(url_hash, "image.png", b"image-bytes") == "image.png"
    assert await manager.save_hash_pdf(url_hash, "document.pdf", b"pdf-bytes") == "document.pdf"
    assert await manager.save_image(3, "legacy.png", b"legacy-image") == "legacy.png"
    assert await manager.save_pdf(3, "legacy.pdf", b"legacy-pdf") == "legacy.pdf"

    assert (manager.get_hash_images_directory(url_hash) / "image.png").read_bytes() == b"image-bytes"
    assert (manager.get_hash_files_directory(url_hash) / "document.pdf").read_bytes() == b"pdf-bytes"
    assert (manager.get_images_directory(3) / "legacy.png").read_bytes() == b"legacy-image"
    assert (manager.get_files_directory(3) / "legacy.pdf").read_bytes() == b"legacy-pdf"


@pytest.mark.asyncio
async def test_storage_manager_saves_hash_and_legacy_page_files(tmp_path) -> None:
    manager = StorageManager("job-1", base_path=str(tmp_path))
    manager.ensure_job_directory()
    url_hash = "d" * 64
    manager.create_hash_directory(url_hash)
    manager.create_page_directory(4)

    await manager.save_hash_json(url_hash, {"url": "https://example.com/hash"})
    await manager.save_hash_content(url_hash, "hash content")
    await manager.save_page_json(4, {"url": "https://example.com/legacy"})
    await manager.save_page_content(4, "")

    hash_dir = manager.get_hash_directory(url_hash)
    legacy_dir = manager.get_page_directory(4)

    assert json.loads((hash_dir / "data.json").read_text(encoding="utf-8")) == {
        "url": "https://example.com/hash",
    }
    assert (hash_dir / "content.md").read_text(encoding="utf-8") == "hash content"
    assert json.loads((legacy_dir / "data.json").read_text(encoding="utf-8")) == {
        "url": "https://example.com/legacy",
    }
    assert (legacy_dir / "content.md").read_text(encoding="utf-8") == ""


@pytest.mark.asyncio
async def test_lifespan_shutdown_cancels_active_crawl_tasks() -> None:
    job_id = "shutdown-job"
    started = asyncio.Event()

    async def pending_job():
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(pending_job())
    await started.wait()

    job_lifecycle.jobs[job_id] = CrawlStatus(
        job_id=job_id,
        status="running",
        message="Crawling in progress...",
        started_at=datetime.now(),
    )
    job_lifecycle.tasks[job_id] = task
    job_lifecycle.pause_events[job_id] = asyncio.Event()

    await job_lifecycle.cancel_active_crawl_tasks()

    assert task.cancelled()
    assert job_lifecycle.jobs[job_id].status == "cancelled"
    assert job_lifecycle.jobs[job_id].message == "Crawl cancelled during service shutdown"
    assert job_id not in job_lifecycle.tasks
    assert job_id not in job_lifecycle.pause_events
    job_lifecycle.jobs.pop(job_id, None)


@pytest.mark.asyncio
async def test_job_lifecycle_marks_all_failed_crawl_as_failed(tmp_path, monkeypatch) -> None:
    job_id = "all-failed-job"
    monkeypatch.setenv("DATA_PATH", str(tmp_path))

    class AllFailedCrawler:
        def __init__(self, config, *, job_id, job_state, storage_manager, pause_event):
            self.config = config
            self.job_id = job_id
            self.job_state = job_state
            self.storage_manager = storage_manager

        async def crawl(self):
            await self.job_state.set_total_urls(1)
            await self.job_state.increment_failed()
            await self.job_state.set_status("completed")
            return {
                "pages_crawled": 0,
                "output_directory": str(self.storage_manager.get_job_directory()),
                "label": None,
            }

    monkeypatch.setattr(job_lifecycle, "CrawlerService", AllFailedCrawler)
    job_lifecycle.jobs[job_id] = CrawlStatus(
        job_id=job_id,
        status="pending",
        message="Crawl job submitted",
        total_pages=1,
        started_at=datetime.now(),
    )

    try:
        await job_lifecycle.run_crawl_job(
            job_id,
            CrawlConfig(job_id=job_id, url="https://example.com", max_pages=1),
        )

        job = job_lifecycle.jobs[job_id]
        assert job.status == "failed"
        assert job.message == "Crawl finished with 0 completed URLs and 1 failed URL(s)."
        assert job.pages_crawled == 0
        assert job.total_pages == 1

        state = json.loads((tmp_path / job_id / "job_state.json").read_text(encoding="utf-8"))
        assert state["status"] == "failed"
        assert state["error"] == "Crawl finished with 0 completed URLs and 1 failed URL(s)."
    finally:
        job_lifecycle.jobs.pop(job_id, None)
        job_lifecycle.tasks.pop(job_id, None)
        job_lifecycle.pause_events.pop(job_id, None)
        job_lifecycle.job_states.pop(job_id, None)


def test_storage_manager_file_browser_lists_info_and_blocks_traversal(tmp_path) -> None:
    manager = StorageManager("job-1", base_path=str(tmp_path))
    manager.ensure_job_directory()
    url_hash = "c" * 64
    page_dir = manager.create_hash_directory(url_hash)
    (page_dir / "content.md").write_text("hello", encoding="utf-8")
    (page_dir / "data.json").write_text("{}", encoding="utf-8")

    files = manager.list_files(relative=True)

    assert files == [
        f"pages/c/c/c/c/{url_hash}/content.md",
        f"pages/c/c/c/c/{url_hash}/data.json",
    ]
    info = manager.get_file_info(f"pages/c/c/c/c/{url_hash}/content.md")
    assert info is not None
    assert info["name"] == "content.md"
    assert info["size"] == 5
    assert info["type"] == "text/markdown"
    assert manager.get_file_path("../outside.txt") is None
    assert manager._get_file_type(page_dir / "unknown.bin") == "application/octet-stream"

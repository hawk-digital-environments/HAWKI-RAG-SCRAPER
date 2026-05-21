import json
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from hawki_crawler.crawler.communication import rabbitmq_service
from hawki_crawler.crawler.communication.rabbitmq_service import RabbitMQCommunicationService
from hawki_crawler.crawler.core.service_sitemap import ServiceSitemapMixin
from hawki_crawler.crawler.core.service_url_policy import ServiceUrlPolicyMixin
from hawki_crawler.crawler.parsing.date_language import DateLanguageService
from hawki_crawler.crawler.policies.url_policy import UrlPolicyService
from hawki_crawler.crawler.sitemap.service import SitemapService
from hawki_crawler.crawler.storage.page_output import build_page_metadata, determine_content_status
from hawki_crawler.crawler.storage.storage_manager import StorageManager


class _PolicyAndSitemapService(ServiceUrlPolicyMixin, ServiceSitemapMixin):
    def __init__(self, *, site_profile=None, crawl_host="example.com") -> None:
        self.site_profile = site_profile or {}
        self.crawl_host = crawl_host
        self.sitemap_map = {}
        self.sitemap_lastmod = {}
        self.url_tracking_manager = None
        self.headers = {}

    def normalize_url(self, url: str) -> str:
        return url.split("#", 1)[0].rstrip("/")


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


class _FailingAioPika:
    async def connect_robust(self, *_args, **_kwargs):
        raise rabbitmq_service.AMQPException("broker unavailable")


@pytest.mark.asyncio
async def test_rabbitmq_connection_failure_is_optional_and_publish_warning_is_not_spammed(caplog) -> None:
    service = RabbitMQCommunicationService(job_id="job-1", host="rabbitmq")
    service._aio_pika = _FailingAioPika()
    service._max_reconnect_attempts = 1

    with caplog.at_level("WARNING"):
        connected = await service.connect()
        first_publish = await service.send_stage(SimpleNamespace(value="stage"))
        second_publish = await service.send_report_progress({"completed": 0})

    assert connected is False
    assert first_publish is False
    assert second_publish is False
    assert caplog.text.count("RabbitMQ is not connected; skipping event publishing for this job") == 1
    assert "broker unavailable" in caplog.text

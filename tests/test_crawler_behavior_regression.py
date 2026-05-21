import json
from types import SimpleNamespace

import pytest

from hawki_crawler.crawler.communication import rabbitmq_service
from hawki_crawler.crawler.communication.rabbitmq_service import RabbitMQCommunicationService
from hawki_crawler.crawler.core.service_sitemap import ServiceSitemapMixin
from hawki_crawler.crawler.core.service_url_policy import ServiceUrlPolicyMixin
from hawki_crawler.crawler.policies.url_policy import UrlPolicyService
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
    service = _PolicyAndSitemapService(
        site_profile={"forbidden": {"hosts": ["blocked.example"]}},
        crawl_host="example.com",
    )

    sitemap_map = service.load_sitemap_map(str(sitemap_file))
    sitemap_urls = service.load_sitemap_urls(str(sitemap_file))

    assert sitemap_map["example.com/page"]["last_modified"] == "2026-01-01"
    assert sitemap_map["example.com/page"]["language"] == "de"
    assert sitemap_map["blocked.example/private"]["last_modified"] == "2026-01-02"
    assert sitemap_urls == ["https://www.example.com/page/"]


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

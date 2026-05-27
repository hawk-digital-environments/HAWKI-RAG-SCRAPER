import hashlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

# Provide a minimal aiofiles fallback for environments where test deps are partial.
try:
    import aiofiles as _aiofiles  # noqa: F401
except ModuleNotFoundError:
    class _AsyncFile:
        def __init__(self, path: str | Path, mode: str) -> None:
            self._path = path
            self._mode = mode
            self._fp = None

        async def __aenter__(self):
            self._fp = open(self._path, self._mode)
            return self

        async def __aexit__(self, exc_type, exc, tb):
            if self._fp:
                self._fp.close()
            return False

        async def write(self, data: bytes) -> int:
            assert self._fp is not None
            return self._fp.write(data)

    def _aiofiles_open(path: str | Path, mode: str = "r", *args, **kwargs):
        return _AsyncFile(path, mode)

    _stub = types.ModuleType("aiofiles")
    _stub.open = _aiofiles_open
    sys.modules["aiofiles"] = _stub

from hawki_crawler.crawler.assets.asset_service_mixin import ServiceParseAssetsMixin
from hawki_crawler.crawler.communication.file_event_publisher import (
    FileEventPublishOutcome,
    FileEventPublisher,
)


class FakeProducer:
    def __init__(self, should_succeed: bool = True) -> None:
        self.should_succeed = should_succeed
        self.published_events = []
        self.closed = False

    async def publish_file_discovered(self, event):
        self.published_events.append(event)
        if self.should_succeed:
            return SimpleNamespace(success=True, error=None)
        return SimpleNamespace(success=False, error="forced publish failure")

    async def close(self) -> None:
        self.closed = True


class _NoopRateLimiter:
    async def acquire(self) -> None:
        return None


class _FakeStream:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def iter_chunked(self, _size: int):
        yield self._data


class _FakeResponse:
    def __init__(self, *, data: bytes, status: int = 200, content_type: str = "application/pdf") -> None:
        self.status = status
        self.headers = {"Content-Type": content_type}
        self.content = _FakeStream(data)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def get(self, *_args, **_kwargs):
        return self._response


class _FakeAssetService(ServiceParseAssetsMixin):
    def __init__(self, base_dir: Path, publisher) -> None:
        self.rate_limiter = _NoopRateLimiter()
        self.headers = {}
        self.config = SimpleNamespace(skip_images=True)
        self.storage_manager = None
        self.file_event_publisher = publisher
        self._base_dir = base_dir
        self.job_id = "Site_Sample10"

    async def create_page_directory(self, page_number: int, create_files_dir: bool = False) -> Path:
        page_dir = self._base_dir / f"page_{page_number:05d}"
        page_dir.mkdir(parents=True, exist_ok=True)
        if create_files_dir:
            (page_dir / "files").mkdir(parents=True, exist_ok=True)
        return page_dir


@pytest.mark.asyncio
async def test_metadata_and_checksum_generation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("COMMUNICATION_ENABLED", "true")
    monkeypatch.setenv("COMMUNICATION_METHOD", "rabbitmq")
    monkeypatch.setenv("JOB_SCHEMA_VERSION", "1")
    monkeypatch.setenv("JOB_SOURCE", "scraper")

    file_path = tmp_path / "report.docx"
    file_path.write_bytes(b"example-doc-content")
    fake_producer = FakeProducer(should_succeed=True)
    publisher = FileEventPublisher(
        producer=fake_producer,
        default_job_id="Site_Sample10",
        job_base_path=tmp_path,
    )

    outcome = await publisher.publish_file_discovered(
        url="https://example.com/docs/report.docx",
        page_url="https://example.com/departments",
        local_path=str(file_path),
        relative_path="pages/hash/files/report.docx",
    )

    assert outcome.success is True
    published = fake_producer.published_events[0]
    assert published.extension == "docx"
    assert published.file_size_bytes == len(b"example-doc-content")
    assert published.content_type
    assert published.checksum_sha256 == hashlib.sha256(b"example-doc-content").hexdigest()


@pytest.mark.asyncio
async def test_disabled_communication_mode_skips_publish(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("COMMUNICATION_ENABLED", "false")
    monkeypatch.setenv("COMMUNICATION_METHOD", "rabbitmq")

    file_path = tmp_path / "sample.pdf"
    file_path.write_bytes(b"pdf-content")
    fake_producer = FakeProducer(should_succeed=True)
    publisher = FileEventPublisher(producer=fake_producer, default_job_id="Site_Sample10")

    outcome = await publisher.publish_file_discovered(
        url="https://example.com/sample.pdf",
        local_path=str(file_path),
        relative_path="files/sample.pdf",
    )

    assert outcome.success is False
    assert outcome.skipped is True
    assert outcome.reason == "communication_disabled"
    assert fake_producer.published_events == []


@pytest.mark.asyncio
async def test_mocked_publish_failure_returns_explicit_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("COMMUNICATION_ENABLED", "true")
    monkeypatch.setenv("COMMUNICATION_METHOD", "rabbitmq")

    file_path = tmp_path / "sample.pdf"
    file_path.write_bytes(b"pdf-content")
    fake_producer = FakeProducer(should_succeed=False)
    publisher = FileEventPublisher(producer=fake_producer, default_job_id="Site_Sample10")

    outcome = await publisher.publish_file_discovered(
        url="https://example.com/sample.pdf",
        local_path=str(file_path),
        relative_path="files/sample.pdf",
    )

    assert outcome.success is False
    assert outcome.skipped is False
    assert outcome.reason == "publish_failure"
    assert "forced publish failure" in (outcome.error or "")


@pytest.mark.asyncio
async def test_duplicate_publish_in_same_run_is_skipped(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("COMMUNICATION_ENABLED", "true")
    monkeypatch.setenv("COMMUNICATION_METHOD", "rabbitmq")

    file_path = tmp_path / "sample.pdf"
    file_path.write_bytes(b"pdf-content")
    fake_producer = FakeProducer(should_succeed=True)
    publisher = FileEventPublisher(producer=fake_producer, default_job_id="Site_Sample10")

    first = await publisher.publish_file_discovered(
        url="https://example.com/sample.pdf",
        local_path=str(file_path),
        relative_path="files/sample.pdf",
    )
    second = await publisher.publish_file_discovered(
        url="https://example.com/sample.pdf",
        local_path=str(file_path),
        relative_path="files/sample.pdf",
    )

    assert first.success is True
    assert second.success is False
    assert second.skipped is True
    assert second.reason == "duplicate_in_run"
    assert len(fake_producer.published_events) == 1


@pytest.mark.asyncio
async def test_saved_file_triggers_event_publication_and_save_flow_still_works(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("COMMUNICATION_ENABLED", "true")
    monkeypatch.setenv("COMMUNICATION_METHOD", "rabbitmq")

    fake_producer = FakeProducer(should_succeed=True)
    publisher = FileEventPublisher(
        producer=fake_producer,
        default_job_id="Site_Sample10",
        job_base_path=tmp_path,
    )
    service = _FakeAssetService(tmp_path, publisher)

    file_bytes = b"hello-docx"
    session = _FakeSession(
        _FakeResponse(
            data=file_bytes,
            status=200,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    )
    result = await service.fetch_and_save_file(
        "https://example.com/files/guide.docx",
        page_number=1,
        session=session,
        url_hash=None,
        page_url="https://example.com/page",
    )

    assert result is not None
    saved_path = Path(result["local_path"])
    assert saved_path.exists()
    assert saved_path.read_bytes() == file_bytes
    assert len(fake_producer.published_events) == 1


@pytest.mark.asyncio
async def test_save_flow_continues_when_event_publish_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("COMMUNICATION_ENABLED", "true")
    monkeypatch.setenv("COMMUNICATION_METHOD", "rabbitmq")

    fake_producer = FakeProducer(should_succeed=False)
    publisher = FileEventPublisher(
        producer=fake_producer,
        default_job_id="Site_Sample10",
        job_base_path=tmp_path,
    )
    service = _FakeAssetService(tmp_path, publisher)

    session = _FakeSession(_FakeResponse(data=b"file-data", status=200, content_type="text/csv"))
    result = await service.fetch_and_save_file(
        "https://example.com/files/data.csv",
        page_number=1,
        session=session,
        url_hash=None,
        page_url="https://example.com/page",
    )

    assert result is not None
    assert Path(result["local_path"]).exists()
    assert len(fake_producer.published_events) == 1

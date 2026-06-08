from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from hawki_crawler.common.pipeline_events import FileDiscoveredEvent


def test_file_discovered_event_schema_validates_required_fields() -> None:
    event = FileDiscoveredEvent(
        event_id=uuid4(),
        job_id=uuid4(),
        schema_version="1",
        event_type="scrape.file.discovered",
        source="scraper",
        url="https://example.com/files/report.pdf",
        local_path="/var/www/html/shared/job-1/pages/a/b/c/d/hash/files/report.pdf",
        relative_path="pages/a/b/c/d/hash/files/report.pdf",
        filename="report.pdf",
        extension="pdf",
        discovered_at=datetime.now(timezone.utc),
    )
    assert event.event_type == "scrape.file.discovered"
    assert event.extension == "pdf"


def test_file_discovered_event_schema_rejects_invalid_event_type() -> None:
    with pytest.raises(ValidationError):
        FileDiscoveredEvent(
            event_id=uuid4(),
            job_id=uuid4(),
            schema_version="1",
            event_type="wrong.event",  # type: ignore[arg-type]
            source="scraper",
            url="https://example.com/files/report.pdf",
            local_path="/tmp/report.pdf",
            relative_path="files/report.pdf",
            filename="report.pdf",
            extension="pdf",
            discovered_at=datetime.now(timezone.utc),
        )


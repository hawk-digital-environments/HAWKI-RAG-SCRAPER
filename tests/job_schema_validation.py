from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.common.job_schema import CrawlJob


def test_crawl_job_schema_validates_required_fields() -> None:
    job = CrawlJob(
        job_id=uuid4(),
        schema_version="1",
        url="https://example.com",
        created_at=datetime.now(timezone.utc),
    )
    assert job.source == "crawler"
    assert job.retry_count == 0
    assert job.max_retries == 3


def test_crawl_job_schema_rejects_invalid_uuid() -> None:
    with pytest.raises(ValidationError):
        CrawlJob(
            job_id="not-a-uuid",
            schema_version="1",
            url="https://example.com",
            created_at=datetime.now(timezone.utc),
        )


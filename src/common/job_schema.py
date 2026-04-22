"""Shared crawl-job schema contract."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CrawlJob(BaseModel):
    """Canonical crawl job contract shared across producer and consumers."""

    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    schema_version: str
    url: str
    source: str = "crawler"
    created_at: datetime
    retry_count: int = 0
    max_retries: int = 3
    trace_id: Optional[str] = None
    payload: Optional[dict[str, Any]] = Field(default=None)


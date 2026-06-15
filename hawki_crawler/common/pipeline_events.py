"""Shared pipeline event schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FileDiscoveredEvent(BaseModel):
    """Canonical event contract for discovered files in the scrape pipeline."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    job_id: UUID
    schema_version: str
    event_type: Literal["scrape.file.discovered"]
    source: str
    url: str
    page_url: Optional[str] = None
    local_path: str
    relative_path: str
    filename: str
    extension: str
    content_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    checksum_sha256: Optional[str] = None
    discovered_at: datetime
    trace_id: Optional[str] = None
    payload: Optional[dict[str, Any]] = None


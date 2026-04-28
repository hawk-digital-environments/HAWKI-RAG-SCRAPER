"""Service helpers for publishing `scrape.file.discovered` pipeline events."""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

from src.common.pipeline_events import FileDiscoveredEvent
from src.rabbitmq.producer import (
    PipelinePublishResult,
    RabbitMQEventProducer,
    RabbitMQEventProducerConfig,
)

SUPPORTED_FILE_EXTENSIONS = {
    "pdf",
    "doc",
    "docx",
    "ppt",
    "pptx",
    "xls",
    "xlsx",
    "txt",
    "csv",
    "md",
    "html",
}


@dataclass(frozen=True)
class FileEventPublishOutcome:
    """High-level result for a file discovered publish attempt."""

    success: bool
    skipped: bool = False
    reason: Optional[str] = None
    event: Optional[FileDiscoveredEvent] = None
    publish_result: Optional[PipelinePublishResult] = None
    error: Optional[str] = None


def _env_enabled() -> bool:
    enabled = os.getenv("COMMUNICATION_ENABLED", "true").strip().lower() == "true"
    method = os.getenv("COMMUNICATION_METHOD", "none").strip().lower()
    return enabled and method == "rabbitmq"


def _normalize_extension(value: Optional[str]) -> str:
    if not value:
        return ""
    trimmed = value.strip().lower()
    return trimmed[1:] if trimmed.startswith(".") else trimmed


def _sha256_file(path: Path) -> Optional[str]:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _to_uuid(value: Optional[UUID | str], *, fallback_key: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str) and value:
        try:
            return UUID(value)
        except ValueError:
            return uuid5(NAMESPACE_URL, fallback_key + ":" + value)
    return uuid4()


class FileEventPublisher:
    """Build and publish `FileDiscoveredEvent` payloads."""

    def __init__(
        self,
        *,
        logger: Optional[logging.Logger] = None,
        producer: Optional[RabbitMQEventProducer] = None,
        default_job_id: Optional[str] = None,
        job_base_path: Optional[str | Path] = None,
    ) -> None:
        self.logger = logger or logging.getLogger("file_event_publisher")
        self._producer = producer
        self._owns_producer = producer is None
        self._enabled = _env_enabled()
        self._disabled_logged = False
        self._seen_dedupe_keys: set[str] = set()
        self._default_job_id = default_job_id
        self._schema_version = os.getenv("JOB_SCHEMA_VERSION", "1")
        self._source = os.getenv("JOB_SOURCE", "scraper")
        outbox = os.getenv("FILE_EVENT_OUTBOX_PATH", "").strip()
        self._outbox_path = Path(outbox) if outbox else None
        self._job_base_path = Path(job_base_path) if job_base_path else None

    def _log_structured(self, level: int, event_name: str, **extra: Any) -> None:
        payload = {"event": event_name}
        payload.update(extra)
        self.logger.log(level, json.dumps(payload, default=str, sort_keys=True))

    def _resolve_relative_path(self, local_path: Path, relative_path: Optional[str]) -> str:
        if relative_path:
            return relative_path
        if self._job_base_path:
            try:
                return str(local_path.resolve().relative_to(self._job_base_path.resolve()))
            except Exception:
                pass
        return local_path.name

    def _resolve_content_type(
        self,
        *,
        content_type: Optional[str],
        filename: str,
        local_path: Path,
    ) -> Optional[str]:
        if content_type:
            return content_type
        guessed, _ = mimetypes.guess_type(filename or str(local_path))
        return guessed

    def _resolve_producer(self) -> RabbitMQEventProducer:
        if self._producer is None:
            self._producer = RabbitMQEventProducer(config=RabbitMQEventProducerConfig.from_env())
        return self._producer

    def _write_outbox(self, event: FileDiscoveredEvent, reason: str) -> None:
        if not self._outbox_path:
            return
        try:
            self._outbox_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "reason": reason,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "event": event.model_dump(mode="json"),
            }
            with self._outbox_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:  # pragma: no cover - filesystem failure path
            self._log_structured(logging.ERROR, "file_event_outbox_write_failed", error=str(exc))

    async def close(self) -> None:
        """Close managed RabbitMQ producer resources."""
        if self._producer and self._owns_producer:
            await self._producer.close()

    async def publish_file_discovered(
        self,
        *,
        url: str,
        local_path: str,
        relative_path: Optional[str] = None,
        filename: Optional[str] = None,
        extension: Optional[str] = None,
        content_type: Optional[str] = None,
        file_size_bytes: Optional[int] = None,
        checksum_sha256: Optional[str] = None,
        page_url: Optional[str] = None,
        job_id: Optional[UUID | str] = None,
        trace_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> FileEventPublishOutcome:
        """
        Build and publish a `scrape.file.discovered` event.

        This method never raises for publish failures; it returns explicit outcome state.
        """
        local_file = Path(local_path)
        resolved_filename = filename or local_file.name
        resolved_extension = _normalize_extension(extension or local_file.suffix)

        if resolved_extension not in SUPPORTED_FILE_EXTENSIONS:
            return FileEventPublishOutcome(
                success=False,
                skipped=True,
                reason=f"unsupported_extension:{resolved_extension or 'none'}",
            )

        if not local_file.exists() or not local_file.is_file():
            return FileEventPublishOutcome(
                success=False,
                skipped=True,
                reason="missing_file",
                error=f"file_not_found:{local_file}",
            )

        size = file_size_bytes
        if size is None:
            try:
                size = local_file.stat().st_size
            except OSError:
                size = None

        checksum = checksum_sha256 or _sha256_file(local_file)
        dedupe_key = "|".join([url, str(local_file.resolve()), checksum or ""])
        if dedupe_key in self._seen_dedupe_keys:
            return FileEventPublishOutcome(success=False, skipped=True, reason="duplicate_in_run")

        discovered_at = datetime.now(timezone.utc)
        resolved_job_id = _to_uuid(job_id or self._default_job_id, fallback_key="scraper-job")
        event = FileDiscoveredEvent(
            event_id=uuid4(),
            job_id=resolved_job_id,
            schema_version=self._schema_version,
            event_type="scrape.file.discovered",
            source=self._source,
            url=url,
            page_url=page_url,
            local_path=str(local_file.resolve()),
            relative_path=self._resolve_relative_path(local_file, relative_path),
            filename=resolved_filename,
            extension=resolved_extension,
            content_type=self._resolve_content_type(
                content_type=content_type, filename=resolved_filename, local_path=local_file
            ),
            file_size_bytes=size,
            checksum_sha256=checksum,
            discovered_at=discovered_at,
            trace_id=trace_id,
            payload=payload,
        )

        if not self._enabled:
            if not self._disabled_logged:
                self._log_structured(
                    logging.INFO,
                    "file_event_communication_disabled",
                    communication_enabled=os.getenv("COMMUNICATION_ENABLED", "true"),
                    communication_method=os.getenv("COMMUNICATION_METHOD", "none"),
                )
                self._disabled_logged = True
            self._write_outbox(event, reason="communication_disabled")
            return FileEventPublishOutcome(
                success=False,
                skipped=True,
                reason="communication_disabled",
                event=event,
            )

        try:
            publish_result = await self._resolve_producer().publish_file_discovered(event)
        except Exception as exc:  # pragma: no cover - integration failure path
            error = str(exc)
            self._log_structured(
                logging.ERROR,
                "file_event_publish_exception",
                event_id=str(event.event_id),
                job_id=str(event.job_id),
                url=event.url,
                local_path=event.local_path,
                error=error,
            )
            self._write_outbox(event, reason="publish_exception")
            return FileEventPublishOutcome(
                success=False,
                skipped=False,
                reason="publish_exception",
                event=event,
                error=error,
            )

        if publish_result.success:
            self._seen_dedupe_keys.add(dedupe_key)
            return FileEventPublishOutcome(
                success=True,
                skipped=False,
                event=event,
                publish_result=publish_result,
            )

        self._write_outbox(event, reason="publish_failure")
        return FileEventPublishOutcome(
            success=False,
            skipped=False,
            reason="publish_failure",
            event=event,
            publish_result=publish_result,
            error=publish_result.error,
        )


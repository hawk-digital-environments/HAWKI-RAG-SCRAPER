"""File event notification for saved crawler assets."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional


class FileEventNotifier:
    """Publish pipeline events for saved file assets."""

    def __init__(
        self,
        *,
        file_event_publisher: Optional[Any],
        job_id: Optional[str],
        logger: Optional[Any] = None,
    ) -> None:
        self.file_event_publisher = file_event_publisher
        self.job_id = job_id
        self.logger = logger or logging.getLogger("crawler")

    async def publish_saved_file_event(
        self,
        *,
        file_url: str,
        page_url: Optional[str],
        file_entry: Dict[str, Any],
    ) -> None:
        """Publish a file-discovered event when communication is available."""
        if not self.file_event_publisher:
            return

        if file_entry.get("incomplete"):
            return

        try:
            outcome = await self.file_event_publisher.publish_file_discovered(
                url=file_url,
                page_url=page_url,
                job_id=self.job_id,
                local_path=file_entry.get("local_path", ""),
                relative_path=file_entry.get("relative_path"),
                filename=file_entry.get("filename"),
                extension=Path(file_entry.get("filename", "")).suffix,
                content_type=file_entry.get("content_type"),
                payload={"asset_type": "file"},
            )
            if not outcome.success and not outcome.skipped:
                self.logger.error(
                    "file_event_publish_failed url=%s local_path=%s reason=%s error=%s",
                    file_url,
                    file_entry.get("local_path"),
                    outcome.reason,
                    outcome.error,
                )
        except Exception as exc:  # pragma: no cover - defensive path
            self.logger.error(
                "file_event_publish_exception url=%s local_path=%s error=%s",
                file_url,
                file_entry.get("local_path"),
                exc,
            )

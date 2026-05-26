from typing import Any, Dict, Optional

from hawki_crawler.crawler.communication.interface import Stage


class ProgressPublisher:
    """Publish crawler progress events through the configured communication service."""

    def __init__(self, communication_service: Optional[Any]) -> None:
        self.communication_service = communication_service

    async def send_stage(
        self,
        stage: Stage,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.communication_service:
            return
        await self.communication_service.send_stage(stage, details)

    async def send_report_progress(self, progress_data: Dict[str, Any]) -> None:
        if not self.communication_service:
            return
        await self.communication_service.send_report_progress(progress_data)

    async def send_summary(self, summary_data: Dict[str, Any]) -> None:
        if not self.communication_service:
            return
        await self.communication_service.send_summary(summary_data)

    async def send_url_completion(
        self,
        *,
        url: str,
        url_hash: str,
        status: str,
        page_number: int,
        started_at: str,
        completed_at: str,
    ) -> None:
        if not self.communication_service:
            return
        await self.communication_service.send_url_completion(
            url=url,
            url_hash=url_hash,
            status=status,
            page_number=page_number,
            started_at=started_at,
            completed_at=completed_at,
        )

from typing import Dict, Any, Optional

from src.crawler.communication.interface import Stage


class ServiceProgressMixin:
    async def _send_stage(self, stage: Stage, details: Optional[Dict[str, Any]] = None):
        if not self.communication_service:
            return
        await self.communication_service.send_stage(stage, details)

    async def _send_report_progress(self, progress_data: Dict[str, Any]):
        if not self.communication_service:
            return
        await self.communication_service.send_report_progress(progress_data)

    async def _send_summary(self, summary_data: Dict[str, Any]):
        if not self.communication_service:
            return
        await self.communication_service.send_summary(summary_data)

    async def _send_url_completion(self, url: str, url_hash: str, status: str, page_number: int,
                                   started_at: str, completed_at: str):
        if not self.communication_service:
            return
        await self.communication_service.send_url_completion(
            url=url,
            url_hash=url_hash,
            status=status,
            page_number=page_number,
            started_at=started_at,
            completed_at=completed_at
        )

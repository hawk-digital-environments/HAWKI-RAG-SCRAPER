from typing import Dict, Any, Optional, TYPE_CHECKING

from hawki_crawler.crawler.communication.interface import Stage

if TYPE_CHECKING:
    from hawki_crawler.crawler.core.protocols import CrawlerServiceProtocol


class ServiceProgressMixin:
    async def send_stage(
        self: "CrawlerServiceProtocol",
        stage: Stage,
        details: Optional[Dict[str, Any]] = None
    ):
        if not self.communication_service:
            return
        await self.communication_service.send_stage(stage, details)

    async def send_report_progress(self: "CrawlerServiceProtocol", progress_data: Dict[str, Any]):
        if not self.communication_service:
            return
        await self.communication_service.send_report_progress(progress_data)

    async def send_summary(self: "CrawlerServiceProtocol", summary_data: Dict[str, Any]):
        if not self.communication_service:
            return
        await self.communication_service.send_summary(summary_data)

    async def _send_url_completion(self: "CrawlerServiceProtocol", url: str, url_hash: str, status: str, page_number: int,
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

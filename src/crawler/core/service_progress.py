from typing import Dict, Any, Optional, TYPE_CHECKING

from hawki_crawler.crawler.communication.interface import Stage
from hawki_crawler.crawler.communication.progress_publisher import ProgressPublisher

if TYPE_CHECKING:
    from hawki_crawler.crawler.core.protocols import ServiceProgressMixinProtocol


class ServiceProgressMixin:
    """Compatibility mixin that delegates progress events to ProgressPublisher."""

    def _progress_publisher(self: "ServiceProgressMixinProtocol") -> ProgressPublisher:
        return ProgressPublisher(getattr(self, "communication_service", None))

    async def send_stage(
        self: "ServiceProgressMixinProtocol",
        stage: Stage,
        details: Optional[Dict[str, Any]] = None
    ):
        await self._progress_publisher().send_stage(stage, details)

    async def send_report_progress(self: "ServiceProgressMixinProtocol", progress_data: Dict[str, Any]):
        await self._progress_publisher().send_report_progress(progress_data)

    async def send_summary(self: "ServiceProgressMixinProtocol", summary_data: Dict[str, Any]):
        await self._progress_publisher().send_summary(summary_data)

    async def _send_url_completion(self: "ServiceProgressMixinProtocol", url: str, url_hash: str, status: str, page_number: int,
                                   started_at: str, completed_at: str):
        await self._progress_publisher().send_url_completion(
            url=url,
            url_hash=url_hash,
            status=status,
            page_number=page_number,
            started_at=started_at,
            completed_at=completed_at
        )

from typing import Any, Dict, Optional

from hawki_crawler.crawler.state.stage import Stage


class ProgressPublisher:
    """No-op progress publisher retained for internal crawler flow hooks."""

    async def send_stage(
        self,
        stage: Stage,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        return None

    async def send_report_progress(self, progress_data: Dict[str, Any]) -> None:
        return None

    async def send_summary(self, summary_data: Dict[str, Any]) -> None:
        return None

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
        return None

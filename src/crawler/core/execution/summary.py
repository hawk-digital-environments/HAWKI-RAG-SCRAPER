"""Final crawl summary handling."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from hawki_crawler.crawler.storage.summary_manager import SummaryManager


async def finalize_crawl_summary(
    *,
    progress_tracker: Optional[Any],
    summary_manager: Optional[Any],
    send_summary: Callable[[Dict[str, Any]], Awaitable[None]],
    job_logger: logging.Logger | logging.LoggerAdapter,
    job_id: Optional[str],
    stage: str,
    output_directory: str | Path,
    error: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Stop progress tracking, persist the final summary, and publish it."""
    if not progress_tracker:
        return None

    await progress_tracker.stop()
    summary_data = await progress_tracker.get_summary()
    if not summary_manager:
        return None

    formatted_summary = SummaryManager.format_summary(
        job_id=job_id,
        stage=stage,
        progress=summary_data,
        output_directory=str(output_directory),
        error=error,
    )
    await summary_manager.save_summary(formatted_summary)
    await send_summary(formatted_summary)
    job_logger.info("\n%s", SummaryManager.format_text_summary(formatted_summary))
    return formatted_summary

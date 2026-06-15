"""Factory for per-job crawler helper services."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from hawki_crawler.common.logging_setup import configure_job_file_logger
from hawki_crawler.crawler.state.progress_tracker import ProgressTracker
from hawki_crawler.crawler.storage.summary_manager import SummaryManager
from hawki_crawler.crawler.storage.url_tracking_manager import URLTrackingManager


@dataclass
class JobHelpers:
    """Per-job collaborators created only when persistent job storage exists."""

    progress_tracker: Optional[ProgressTracker]
    url_tracking_manager: Optional[URLTrackingManager]
    summary_manager: Optional[SummaryManager]
    job_logger: logging.LoggerAdapter


def build_job_helpers(
    *,
    job_id: Optional[str],
    storage_manager: Optional[Any],
    site_profile: dict[str, Any],
    default_logger: logging.LoggerAdapter,
) -> JobHelpers:
    """Create per-job services and preserve no-storage fallback behavior."""
    helpers = JobHelpers(
        progress_tracker=None,
        url_tracking_manager=None,
        summary_manager=None,
        job_logger=default_logger,
    )
    if not job_id or not storage_manager:
        return helpers

    storage_manager.ensure_job_directory()
    job_directory = storage_manager.get_job_directory()
    base_path = str(storage_manager.base_path)
    forbidden = site_profile.get("forbidden", {})

    helpers.progress_tracker = ProgressTracker()
    helpers.url_tracking_manager = URLTrackingManager(
        job_id=job_id,
        base_path=base_path,
        forbidden_hosts=forbidden.get("hosts"),
        forbidden_patterns=forbidden.get("url_patterns"),
        forbidden_rules_file=forbidden.get("rules_file"),
    )
    helpers.summary_manager = SummaryManager(job_id=job_id, base_path=base_path)
    helpers.job_logger = configure_job_file_logger(job_id, job_directory / "crawler.log")
    return helpers

"""Default runtime settings for crawler service initialization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse


DEFAULT_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}


@dataclass(frozen=True)
class BrowserRestartDefaults:
    """Browser restart thresholds used by the crawl execution loop."""

    max_restarts: int = 3
    interval_seconds: int = 3600
    enabled: bool = False


@dataclass(frozen=True)
class MemoryWatchdogDefaults:
    """Memory watchdog thresholds used by the crawl runtime helpers."""

    enabled: bool = True
    restart_threshold: float = 0.9
    resume_threshold: float = 0.1
    restart_wait_seconds: int = 300


BROWSER_RESTART_DEFAULTS = BrowserRestartDefaults()
MEMORY_WATCHDOG_DEFAULTS = MemoryWatchdogDefaults()


def default_http_headers() -> dict[str, str]:
    """Return a fresh copy of the default HTTP/browser request headers."""
    return dict(DEFAULT_HTTP_HEADERS)


def build_output_label(url: str, now: Optional[datetime] = None) -> str:
    """Build the legacy default output label from URL domain and timestamp."""
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    domain = urlparse(url).netloc.replace(".", "_")
    return f"{domain}_{timestamp}"


def resolve_output_directory(
    *,
    config: Any,
    storage_manager: Optional[Any],
    now: Optional[datetime] = None,
) -> Path:
    """Resolve output directory while preserving the legacy config-label mutation."""
    if not config.label:
        config.label = build_output_label(str(config.url), now=now)

    if storage_manager:
        return storage_manager.get_job_directory()
    return Path(config.output_dir) / config.label

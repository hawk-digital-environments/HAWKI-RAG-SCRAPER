"""Mutable crawl runtime state construction."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from hawki_crawler.crawler.core.runtime_defaults import (
    BROWSER_RESTART_DEFAULTS,
    MEMORY_WATCHDOG_DEFAULTS,
)
from hawki_crawler.crawler.core.service_rate import RateLimiter
from hawki_crawler.crawler.models import CrawlConfig


@dataclass
class CrawlRuntimeState:
    """Mutable state used by the crawler execution and runtime mixins."""

    visited_urls: Set[str]
    to_visit: List[str]
    url_depth: Dict[str, int]
    url_source: Dict[str, str]
    pages_data: List[Dict[str, Any]]
    rate_limiter: RateLimiter
    semaphore: asyncio.Semaphore
    page_counter: int
    counter_lock: asyncio.Lock
    allow_over_max_pages: bool
    consecutive_5xx: int
    consecutive_5xx_lock: asyncio.Lock
    abort_crawl: bool
    abort_reason: Optional[str]
    abort_lock: asyncio.Lock
    pause_event: Optional[asyncio.Event]
    pause_logged: bool
    restart_crawler: bool
    restart_urls: List[str]
    restart_lock: asyncio.Lock
    browser_restart_count: int
    max_browser_restarts: int
    browser_restart_interval_seconds: int
    browser_last_restart: float
    enable_browser_restarts: bool
    restart_reason: Optional[str]
    enable_memory_watchdog: bool
    memory_restart_threshold: float
    memory_resume_threshold: float
    memory_restart_wait_seconds: int


def build_crawl_runtime_state(
    *,
    config: CrawlConfig,
    pause_event: Optional[asyncio.Event],
    browser_last_restart: Optional[float] = None,
) -> CrawlRuntimeState:
    """Create the mutable crawl state attached to a crawler service instance."""
    return CrawlRuntimeState(
        visited_urls=set(),
        to_visit=[],
        url_depth={},
        url_source={},
        pages_data=[],
        rate_limiter=RateLimiter(config.max_rpm, config.request_delay),
        semaphore=asyncio.Semaphore(config.max_concurrency),
        page_counter=0,
        counter_lock=asyncio.Lock(),
        allow_over_max_pages=False,
        consecutive_5xx=0,
        consecutive_5xx_lock=asyncio.Lock(),
        abort_crawl=False,
        abort_reason=None,
        abort_lock=asyncio.Lock(),
        pause_event=pause_event,
        pause_logged=False,
        restart_crawler=False,
        restart_urls=[],
        restart_lock=asyncio.Lock(),
        browser_restart_count=0,
        max_browser_restarts=BROWSER_RESTART_DEFAULTS.max_restarts,
        browser_restart_interval_seconds=BROWSER_RESTART_DEFAULTS.interval_seconds,
        browser_last_restart=time.monotonic() if browser_last_restart is None else browser_last_restart,
        enable_browser_restarts=BROWSER_RESTART_DEFAULTS.enabled,
        restart_reason=None,
        enable_memory_watchdog=MEMORY_WATCHDOG_DEFAULTS.enabled,
        memory_restart_threshold=MEMORY_WATCHDOG_DEFAULTS.restart_threshold,
        memory_resume_threshold=MEMORY_WATCHDOG_DEFAULTS.resume_threshold,
        memory_restart_wait_seconds=MEMORY_WATCHDOG_DEFAULTS.restart_wait_seconds,
    )

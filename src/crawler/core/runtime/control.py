"""Runtime crawl control helpers."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, MutableSequence


async def request_safe_stop(
    *,
    abort_lock: asyncio.Lock,
    is_aborted: Callable[[], bool],
    mark_aborted: Callable[[str], None],
    pending_urls: MutableSequence[str],
    reason: str,
) -> None:
    """Stop future crawl work and record the abort reason."""
    async with abort_lock:
        if is_aborted():
            return

        mark_aborted(reason)
        # Clearing the queue prevents new URLs from being scheduled after a fatal condition.
        pending_urls.clear()


async def request_browser_restart(
    *,
    enabled: bool,
    restart_lock: asyncio.Lock,
    restart_urls: MutableSequence[str],
    mark_restart_requested: Callable[[str], None],
    url: str,
) -> None:
    """Ask the crawl loop to restart browser work before retrying a URL."""
    if not enabled:
        return

    async with restart_lock:
        if url not in restart_urls:
            restart_urls.append(url)
        mark_restart_requested("browser_closed")


async def update_total_url_counts(
    *,
    new_total: int,
    job_state: Any,
    progress_tracker: Any,
) -> None:
    """Increase persisted and published total URL counts when discovery expands work."""
    if new_total <= 0:
        return

    if job_state:
        snapshot = await job_state.get_snapshot()
        if new_total > snapshot.total_urls:
            await job_state.set_total_urls(new_total)

    if progress_tracker:
        progress = await progress_tracker.get_progress()
        if new_total > progress["total_urls"]:
            await progress_tracker.set_total_urls(new_total)

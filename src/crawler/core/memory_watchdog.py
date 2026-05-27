"""Container memory watchdog helpers for crawl runtime."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Awaitable, Callable, Iterable, Optional


DEFAULT_CGROUP_MEMORY_PATHS = (
    (Path("/sys/fs/cgroup/memory.current"), Path("/sys/fs/cgroup/memory.max")),
    (
        Path("/sys/fs/cgroup/memory/memory.usage_in_bytes"),
        Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    ),
)


def read_cgroup_memory_usage_ratio(
    paths: Iterable[tuple[str | Path, str | Path]] = DEFAULT_CGROUP_MEMORY_PATHS,
) -> Optional[float]:
    """Return cgroup memory usage ratio, or None if it cannot be determined."""
    for current_path, max_path in paths:
        try:
            current = Path(current_path).read_text(encoding="utf-8").strip()
            limit = Path(max_path).read_text(encoding="utf-8").strip()
            if limit == "max":
                return None

            current_val = float(current)
            limit_val = float(limit)
            if limit_val <= 0:
                return None

            return current_val / limit_val
        except Exception:
            continue

    return None


async def wait_until_memory_relief(
    *,
    enable_memory_watchdog: bool,
    memory_resume_threshold: float,
    memory_restart_wait_seconds: int,
    get_memory_usage_ratio: Callable[[], Optional[float]],
    job_logger: logging.Logger | logging.LoggerAdapter,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Wait until memory usage drops below the resume threshold or times out."""
    if not enable_memory_watchdog:
        return

    deadline = monotonic() + memory_restart_wait_seconds
    while True:
        ratio = get_memory_usage_ratio()
        if ratio is None or ratio <= memory_resume_threshold:
            return

        if monotonic() >= deadline:
            job_logger.error(
                "memory watchdog timeout: usage %.1f%% still above resume threshold",
                ratio * 100 if ratio is not None else -1,
            )
            return

        await sleep(5)

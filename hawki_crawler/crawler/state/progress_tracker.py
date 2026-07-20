"""
ProgressTracker - Crawl Progress State
======================================
This class manages local progress tracking for a crawl job.

Why this exists:
- Aggregates progress information efficiently
- Ensures consistent progress reporting even under high load
- Tracks scrape statistics (sessions, requests, errors, warnings)

Lifecycle:
- Created when a crawl job starts
- Updated on every URL processing event
- Final summary emitted when job completes
"""

import asyncio
import time
from typing import Dict, Any
from datetime import datetime

class ProgressTracker:
    """
    Manages rate-limited progress tracking and emission.

    Tracks:
    - Total URLs to process
    - Completed URLs
    - Failed URLs
    - Current stage
    - Statistics (sessions, requests, errors, warnings)
    """

    def __init__(self, emit_interval: float = 1.0):
        """
        Initialize progress tracker.

        Args:
            emit_interval: Minimum interval between internal progress snapshots.
        """
        self.emit_interval = emit_interval
        self.last_emit_time = 0
        self.lock = asyncio.Lock()

        # Progress state
        self.stage = "initialization"  # initialization, scraping, completed, failed
        self.total_urls = 0
        self.completed_urls = 0
        self.failed_urls = 0
        self.current_url = None

        # Last URL completion details
        self.last_url_completion = None  # {url, url_hash, status, page_number, started_at, completed_at}

        # Statistics
        self.stats = {
            "sessions": 0,
            "requests": 0,
            "errors": 0,
            "warnings": 0,
            "pdfs_downloaded": 0,
            "images_downloaded": 0
        }

        # Timing
        self.started_at = None
        self.completed_at = None

        # Background emission task
        self._emit_task = None
        self._should_emit = False

    async def start(self):
        """Start the background emission task."""
        self.started_at = datetime.utcnow().isoformat() + "Z"
        self._emit_task = asyncio.create_task(self._emit_loop())

    async def stop(self):
        """Stop the background emission task and emit final state."""
        if self._emit_task:
            self._emit_task.cancel()
            try:
                await self._emit_task
            except asyncio.CancelledError:
                pass

        # Emit final state
        await self._emit_progress(force=True)

    async def set_stage(self, stage: str):
        """
        Set current processing stage.

        Args:
            stage: One of "initialization", "scraping", "completed", "failed"
        """
        async with self.lock:
            self.stage = stage

            if stage in ["completed", "failed"]:
                self.completed_at = datetime.utcnow().isoformat() + "Z"

        # Refresh immediately on stage change (outside the lock to avoid deadlock).
        await self._emit_progress(force=True)

    async def set_total_urls(self, total: int):
        """Set total number of URLs to process."""
        async with self.lock:
            self.total_urls = total
            self._should_emit = True

    async def set_current_url(self, url: str):
        """Set the URL currently being processed."""
        async with self.lock:
            self.current_url = url
            self._should_emit = True

    async def set_url_completion(self, url: str, url_hash: str, status: str,
                                 page_number: int, started_at: str, completed_at: str):
        """
        Record details of the most recently completed URL.
        """
        async with self.lock:
            self.last_url_completion = {
                "url": url,
                "url_hash": url_hash,
                "status": status,
                "page_number": page_number,
                "started_at": started_at,
                "completed_at": completed_at
            }
            self._should_emit = True

    async def increment_completed(self):
        """Increment completed URL count."""
        async with self.lock:
            self.completed_urls += 1
            self._should_emit = True

    async def increment_failed(self):
        """Increment failed URL count."""
        async with self.lock:
            self.failed_urls += 1
            self._should_emit = True

    async def decrement_failed(self):
        """Decrement failed URL count."""
        async with self.lock:
            if self.failed_urls > 0:
                self.failed_urls -= 1
                self._should_emit = True

    async def increment_requests(self):
        """Increment request count."""
        async with self.lock:
            self.stats["requests"] += 1
            self._should_emit = True

    async def increment_errors(self):
        """Increment error count."""
        async with self.lock:
            self.stats["errors"] += 1
            self._should_emit = True

    async def increment_warnings(self):
        """Increment warning count."""
        async with self.lock:
            self.stats["warnings"] += 1
            self._should_emit = True

    async def increment_pdfs(self, count: int = 1):
        """Increment PDF download count."""
        async with self.lock:
            self.stats["pdfs_downloaded"] += count
            self._should_emit = True

    async def increment_images(self, count: int = 1):
        """Increment image download count."""
        async with self.lock:
            self.stats["images_downloaded"] += count
            self._should_emit = True

    async def increment_sessions(self):
        """Increment session count."""
        async with self.lock:
            self.stats["sessions"] += 1
            self._should_emit = True

    async def get_progress(self) -> Dict[str, Any]:
        """
        Get current progress state.

        Returns:
            Dictionary with progress information
        """
        async with self.lock:
            stats = self.stats.copy()
            # Include completed/failed in stats for easier aggregation downstream
            stats["completed_urls"] = self.completed_urls
            stats["failed_urls"] = self.failed_urls

            progress = {
                "stage": self.stage,
                "total_urls": self.total_urls,
                "completed_urls": self.completed_urls,
                "failed_urls": self.failed_urls,
                "processing_urls": max(0, self.total_urls - self.completed_urls - self.failed_urls),
                "current_url": self.current_url,
                "progress_percentage": self._calculate_percentage(),
                "stats": stats,
                "started_at": self.started_at,
                "completed_at": self.completed_at
            }

            # Add last URL completion when available
            if self.last_url_completion:
                progress["url_completion"] = self.last_url_completion.copy()

            return progress

    async def get_summary(self) -> Dict[str, Any]:
        """
        Get final summary (called when job completes).

        Returns:
            Dictionary with complete job summary
        """
        progress = await self.get_progress()

        # Calculate duration
        duration_seconds = None
        if self.started_at and self.completed_at:
            try:
                start = datetime.fromisoformat(self.started_at.replace('Z', '+00:00'))
                end = datetime.fromisoformat(self.completed_at.replace('Z', '+00:00'))
                duration_seconds = (end - start).total_seconds()
            except Exception:
                pass

        summary = {
            **progress,
            "duration_seconds": duration_seconds,
            "success_rate": self._calculate_success_rate()
        }

        return summary

    def _calculate_percentage(self) -> float:
        """Calculate progress percentage."""
        if self.total_urls == 0:
            return 0.0

        processed = self.completed_urls + self.failed_urls
        return round((processed / self.total_urls) * 100, 2)

    def _calculate_success_rate(self) -> float:
        """Calculate success rate."""
        total_processed = self.completed_urls + self.failed_urls
        if total_processed == 0:
            return 0.0

        return round((self.completed_urls / total_processed) * 100, 2)

    async def _emit_loop(self):
        """Background task that emits progress at regular intervals."""
        try:
            while True:
                await asyncio.sleep(self.emit_interval)

                should_emit = False
                async with self.lock:
                    if self._should_emit:
                        should_emit = True
                        self._should_emit = False

                # Emit outside the lock to avoid deadlock
                if should_emit:
                    await self._emit_progress(force=False)
        except asyncio.CancelledError:
            pass

    async def _emit_progress(self, force: bool = False):
        """
        Refresh progress timestamp if enough time has passed.

        Args:
            force: If True, emit regardless of time interval
        """
        current_time = time.time()

        # Check if enough time has passed (unless forced)
        if not force and (current_time - self.last_emit_time) < self.emit_interval:
            return

        await self.get_progress()

        # Update last emit time
        self.last_emit_time = current_time

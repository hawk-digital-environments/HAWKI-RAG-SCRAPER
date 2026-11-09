"""
JobState - Unified Job State Management
========================================
This class provides a centralized, observable job state object that:
- Represents the job_state.json structure
- Automatically persists changes to disk
- Notifies in-process observers when state changes
- Thread-safe with asyncio locks

This replaces the old JobStateManager with a more object-oriented approach
where the state itself is the primary object, not just a manager.
"""

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from hawki_crawler.runtime.writes import AsyncFile, assert_writable
from hawki_crawler.runtime.writes import mkdir as guarded_mkdir

LOGGER = logging.getLogger("crawler.job_state")


@dataclass
class JobStateData:
    """
    Data structure representing the job state.
    This matches the job_state.json schema.
    """
    job_id: str
    status: str = "pending"
    total_urls: int = 0
    completed_urls: int = 0
    failed_urls: int = 0
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None
    current_url: Optional[str] = None
    output_directory: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


class JobState:
    """
    Observable job state object with automatic persistence and notification.

    This class uses the observer pattern to notify in-process listeners when
    state changes.

    Usage:
        job_state = JobState(job_id="123", base_path="/var/www/html/shared")
        await job_state.initialize()

        # Register observer
        job_state.add_observer(lambda state: print(f"State changed: {state}"))

        # Update state (automatically persists and notifies observers)
        await job_state.set_status("running")
        await job_state.increment_completed()
    """

    def __init__(self, job_id: str, base_path: str = "/var/www/html/shared"):
        """
        Initialize job state.

        Args:
            job_id: Unique identifier for the job
            base_path: Base directory for job data (default: /var/www/html/shared)
        """
        self.base_path = Path(base_path)
        self.job_dir = self.base_path / job_id
        self.state_file = self.job_dir / "job_state.json"
        self._lock = asyncio.Lock()
        self._observers: List[Callable[[JobStateData], Any]] = []

        # Initialize state data
        self._data = JobStateData(
            job_id=job_id,
            output_directory=str(self.job_dir)
        )

    def add_observer(self, observer: Callable[[JobStateData], Any]):
        """
        Add an observer that will be notified when state changes.

        Args:
            observer: Callable that receives JobStateData when state changes
        """
        self._observers.append(observer)

    def remove_observer(self, observer: Callable[[JobStateData], Any]):
        """Remove an observer."""
        if observer in self._observers:
            self._observers.remove(observer)

    async def _notify_observers(self):
        """Notify all observers of state change."""
        for observer in self._observers:
            try:
                # Support both sync and async observers
                result = observer(self._data)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                LOGGER.warning(
                    "Observer notification failed for %s: %s",
                    self._data.job_id,
                    e,
                    extra={"job_id": self._data.job_id},
                )

    async def initialize(self):
        """
        Initialize the job directory and create initial state file.
        Must be called before using the job state.
        """
        assert_writable(self.state_file)
        async with self._lock:
            assert_writable(self.state_file)
            if self.state_file.exists():
                try:
                    async with AsyncFile(self.state_file, 'r', encoding='utf-8') as f:
                        assert_writable(self.state_file)
                        content = await f.read()
                        data = json.loads(content)
                        self._data = JobStateData(**data)
                        if not self._data.output_directory:
                            self._data.output_directory = str(self.job_dir)
                        return
                except Exception as e:
                    LOGGER.warning(
                        "Failed to read job state for %s: %s",
                        self._data.job_id,
                        e,
                        extra={"job_id": self._data.job_id},
                    )

            # Create job directory
            guarded_mkdir(self.job_dir, parents=True, exist_ok=True)

            # Set initial timestamps
            now = datetime.utcnow().isoformat() + "Z"
            self._data.started_at = now
            self._data.updated_at = now

            # Write initial state
            await self._write_state()

    async def _write_state(self):
        """Write current state to disk."""
        assert_writable(self.state_file)
        try:
            async with AsyncFile(self.state_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(self._data.to_dict(), indent=2, ensure_ascii=False))
        except Exception as e:
            LOGGER.warning(
                "Failed to write job state for %s: %s",
                self._data.job_id,
                e,
                extra={"job_id": self._data.job_id},
            )

    async def _update_timestamp_and_persist(self):
        """Update timestamp, persist to disk, and notify observers."""
        self._data.updated_at = datetime.utcnow().isoformat() + "Z"
        await self._write_state()
        await self._notify_observers()

    # Property accessors
    @property
    def job_id(self) -> str:
        """Get job ID."""
        return self._data.job_id

    @property
    def status(self) -> str:
        """Get current status."""
        return self._data.status

    @property
    def total_urls(self) -> int:
        """Get total URLs."""
        return self._data.total_urls

    @property
    def completed_urls(self) -> int:
        """Get completed URLs count."""
        return self._data.completed_urls

    @property
    def failed_urls(self) -> int:
        """Get failed URLs count."""
        return self._data.failed_urls

    @property
    def current_url(self) -> Optional[str]:
        """Get current URL being processed."""
        return self._data.current_url

    @property
    def error(self) -> Optional[str]:
        """Get error message if any."""
        return self._data.error

    # State modification methods
    async def set_status(self, status: str):
        """
        Set job status.

        Args:
            status: One of "pending", "running", "completed", "failed"
        """
        assert_writable(self.state_file)
        async with self._lock:
            assert_writable(self.state_file)
            self._data.status = status

            if status in ["completed", "failed", "cancelled"]:
                self._data.completed_at = datetime.utcnow().isoformat() + "Z"

            await self._update_timestamp_and_persist()

    async def set_total_urls(self, total: int):
        """Set the total number of URLs to crawl."""
        assert_writable(self.state_file)
        async with self._lock:
            assert_writable(self.state_file)
            self._data.total_urls = total
            await self._update_timestamp_and_persist()

    async def set_current_url(self, url: str):
        """Set the URL currently being processed."""
        assert_writable(self.state_file)
        async with self._lock:
            assert_writable(self.state_file)
            self._data.current_url = url
            await self._update_timestamp_and_persist()

    async def increment_completed(self):
        """Increment the count of completed URLs."""
        assert_writable(self.state_file)
        async with self._lock:
            assert_writable(self.state_file)
            self._data.completed_urls += 1
            processed = self._data.completed_urls + self._data.failed_urls
            if processed > self._data.total_urls:
                self._data.total_urls = processed
            await self._update_timestamp_and_persist()

    async def increment_failed(self):
        """Increment the count of failed URLs."""
        assert_writable(self.state_file)
        async with self._lock:
            assert_writable(self.state_file)
            self._data.failed_urls += 1
            processed = self._data.completed_urls + self._data.failed_urls
            if processed > self._data.total_urls:
                self._data.total_urls = processed
            await self._update_timestamp_and_persist()

    async def decrement_failed(self):
        """Decrement the count of failed URLs."""
        assert_writable(self.state_file)
        async with self._lock:
            assert_writable(self.state_file)
            if self._data.failed_urls > 0:
                self._data.failed_urls -= 1
                await self._update_timestamp_and_persist()

    async def set_error(self, error: str):
        """Set error message and mark job as failed."""
        assert_writable(self.state_file)
        async with self._lock:
            assert_writable(self.state_file)
            self._data.error = error
            self._data.status = "failed"
            self._data.completed_at = datetime.utcnow().isoformat() + "Z"
            self._data.updated_at = self._data.completed_at
            await self._write_state()
            await self._notify_observers()

    async def get_snapshot(self) -> JobStateData:
        """Get a snapshot of the current state."""
        async with self._lock:
            # Return a copy to prevent external modification
            return JobStateData(**self._data.to_dict())

    async def get_dict(self) -> Dict[str, Any]:
        """Get state as dictionary."""
        async with self._lock:
            return self._data.to_dict()

    async def read_from_disk(self) -> Dict[str, Any]:
        """
        Read state from disk.
        Useful for recovery or external monitoring.
        """
        try:
            if self.state_file.exists():
                async with AsyncFile(self.state_file, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    return json.loads(content)
        except Exception as e:
            LOGGER.warning(
                "Failed to read job state for %s: %s",
                self._data.job_id,
                e,
                extra={"job_id": self._data.job_id},
            )

        return self._data.to_dict()

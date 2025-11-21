"""
JobStateManager - State Tracking Layer
======================================
This class manages persistent job state and metadata.
It writes job status to disk so external systems (Laravel) can read progress.

Why this exists:
- Provides persistent state that survives container restarts
- Allows Laravel to monitor job progress without WebSocket connection
- Maintains a single source of truth for job status

Lifecycle:
- Created when a crawl job starts
- Updated on every significant event
- Final state written when job completes or fails
"""

import json
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
import aiofiles


class JobStateManager:
    """
    Manages persistent job state stored as JSON files.

    The state file contains:
    - job_id: Unique job identifier
    - status: current, completed, failed
    - total_urls: Total URLs to crawl
    - completed_urls: URLs completed so far
    - failed_urls: URLs that failed
    - started_at: ISO timestamp
    - updated_at: ISO timestamp
    - completed_at: ISO timestamp (when finished)
    - current_url: URL being processed
    - output_directory: Where files are stored
    - error: Error message if failed
    """

    def __init__(self, job_id: str, base_path: str = "/app/data/jobs"):
        """
        Initialize job state manager.

        Args:
            job_id: Unique identifier for the job
            base_path: Base directory for job data (default: /app/data/jobs)
        """
        self.job_id = job_id
        self.base_path = Path(base_path)
        self.job_dir = self.base_path / job_id
        self.state_file = self.job_dir / "job_state.json"
        self.lock = asyncio.Lock()

        # In-memory state
        self.state = {
            "job_id": job_id,
            "status": "pending",
            "total_urls": 0,
            "completed_urls": 0,
            "failed_urls": 0,
            "started_at": None,
            "updated_at": None,
            "completed_at": None,
            "current_url": None,
            "output_directory": str(self.job_dir),
            "error": None
        }

    async def initialize(self):
        """
        Initialize the job directory and create initial state file.
        Must be called before using the manager.
        """
        # Create job directory
        self.job_dir.mkdir(parents=True, exist_ok=True)

        # Set initial timestamps
        self.state["started_at"] = datetime.utcnow().isoformat() + "Z"
        self.state["updated_at"] = self.state["started_at"]

        # Write initial state
        await self._write_state()

    async def set_total_urls(self, total: int):
        """Set the total number of URLs to crawl."""
        async with self.lock:
            self.state["total_urls"] = total
            self.state["updated_at"] = datetime.utcnow().isoformat() + "Z"
            await self._write_state()

    async def set_status(self, status: str):
        """
        Set job status.

        Args:
            status: One of "pending", "running", "completed", "failed"
        """
        async with self.lock:
            self.state["status"] = status
            self.state["updated_at"] = datetime.utcnow().isoformat() + "Z"

            if status in ["completed", "failed"]:
                self.state["completed_at"] = self.state["updated_at"]

            await self._write_state()

    async def set_current_url(self, url: str):
        """Set the URL currently being processed."""
        async with self.lock:
            self.state["current_url"] = url
            self.state["updated_at"] = datetime.utcnow().isoformat() + "Z"
            await self._write_state()

    async def increment_completed(self):
        """Increment the count of completed URLs."""
        async with self.lock:
            self.state["completed_urls"] += 1
            self.state["updated_at"] = datetime.utcnow().isoformat() + "Z"
            await self._write_state()

    async def increment_failed(self):
        """Increment the count of failed URLs."""
        async with self.lock:
            self.state["failed_urls"] += 1
            self.state["updated_at"] = datetime.utcnow().isoformat() + "Z"
            await self._write_state()

    async def set_error(self, error: str):
        """Set error message and mark job as failed."""
        async with self.lock:
            self.state["error"] = error
            self.state["status"] = "failed"
            self.state["completed_at"] = datetime.utcnow().isoformat() + "Z"
            self.state["updated_at"] = self.state["completed_at"]
            await self._write_state()

    async def get_state(self) -> Dict[str, Any]:
        """Get current state snapshot."""
        async with self.lock:
            return self.state.copy()

    async def _write_state(self):
        """
        Write current state to disk.
        Internal method called automatically by update methods.
        """
        try:
            async with aiofiles.open(self.state_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(self.state, indent=2, ensure_ascii=False))
        except Exception as e:
            # Log error but don't fail the job
            print(f"Warning: Failed to write job state for {self.job_id}: {e}")

    async def read_state(self) -> Dict[str, Any]:
        """
        Read state from disk.
        Useful for recovery or external monitoring.
        """
        try:
            if self.state_file.exists():
                async with aiofiles.open(self.state_file, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    return json.loads(content)
        except Exception as e:
            print(f"Warning: Failed to read job state for {self.job_id}: {e}")

        return self.state.copy()

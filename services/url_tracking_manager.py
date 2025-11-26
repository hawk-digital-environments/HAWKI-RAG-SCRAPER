"""
URLTrackingManager - URL State Tracking Layer
==============================================
This class manages URL discovery, dates, and processing state.
It maintains a JSON file with all discovered URLs and their metadata.

Why this exists:
- Track all URLs discovered from sitemap or during crawling
- Store both sitemap dates and header dates for comparison
- Provide single source of truth for URL processing state
- Enable resume functionality and progress monitoring

URL State Structure:
{
    "url": {
        "status": "pending|processing|completed|failed",
        "sitemap_date": "ISO-8601 timestamp or null",
        "header_last_modified": "ISO-8601 timestamp or null",
        "header_date": "ISO-8601 timestamp or null",
        "page_number": 123,
        "error": "error message or null",
        "discovered_at": "ISO-8601 timestamp",
        "completed_at": "ISO-8601 timestamp or null"
    }
}

Lifecycle:
- Created when a crawl job starts
- Updated after sitemap parsing (bulk URL addition)
- Updated during crawling (status changes, date extraction)
- Final state written when job completes or fails
"""

import json
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
import aiofiles


class URLTrackingManager:
    """
    Manages URL tracking state stored as a JSON file.

    Provides methods to:
    - Add URLs from sitemap with lastmod dates
    - Update URL status during processing
    - Add dates from page headers
    - Query URL states
    """

    def __init__(self, job_id: str, base_path: str = "/app/data/jobs"):
        """
        Initialize URL tracking manager.

        Args:
            job_id: Unique identifier for the job
            base_path: Base directory for job data (default: /app/data/jobs)
        """
        self.job_id = job_id
        self.base_path = Path(base_path)
        self.job_dir = self.base_path / job_id
        self.tracking_file = self.job_dir / "urls_tracking.json"
        self.lock = asyncio.Lock()

        # In-memory state
        self.urls: Dict[str, Dict[str, Any]] = {}

    async def initialize(self):
        """
        Initialize the tracking file.
        Must be called before using the manager.
        """
        # Create job directory if needed
        self.job_dir.mkdir(parents=True, exist_ok=True)

        # Write initial empty state
        await self._write_state()

    async def add_urls_from_sitemap(self, urls_with_dates: Dict[str, Optional[str]]):
        """
        Add multiple URLs discovered from sitemap.

        Args:
            urls_with_dates: Dictionary mapping URL to lastmod date (or None)
        """
        async with self.lock:
            timestamp = datetime.utcnow().isoformat() + "Z"

            for url, sitemap_date in urls_with_dates.items():
                if url not in self.urls:
                    self.urls[url] = {
                        "status": "pending",
                        "sitemap_date": sitemap_date,
                        "header_last_modified": None,
                        "header_date": None,
                        "page_number": None,
                        "error": None,
                        "discovered_at": timestamp,
                        "completed_at": None
                    }

            await self._write_state()

    async def add_url(self, url: str, source: str = "discovery"):
        """
        Add a single URL (typically from discovery during crawling).

        Args:
            url: URL to add
            source: Source of discovery (e.g., "discovery", "seed")
        """
        async with self.lock:
            if url not in self.urls:
                timestamp = datetime.utcnow().isoformat() + "Z"
                self.urls[url] = {
                    "status": "pending",
                    "sitemap_date": None,
                    "header_last_modified": None,
                    "header_date": None,
                    "page_number": None,
                    "error": None,
                    "discovered_at": timestamp,
                    "completed_at": None,
                    "source": source
                }
                await self._write_state()

    async def set_processing(self, url: str, page_number: int):
        """
        Mark URL as currently being processed.

        Args:
            url: URL being processed
            page_number: Page number assigned to this URL
        """
        async with self.lock:
            if url in self.urls:
                self.urls[url]["status"] = "processing"
                self.urls[url]["page_number"] = page_number
                await self._write_state()

    async def set_completed(self, url: str, header_dates: Optional[Dict[str, Optional[str]]] = None):
        """
        Mark URL as successfully completed.

        Args:
            url: URL that was completed
            header_dates: Optional dictionary with 'last_modified' and 'date' keys
        """
        async with self.lock:
            if url in self.urls:
                timestamp = datetime.utcnow().isoformat() + "Z"
                self.urls[url]["status"] = "completed"
                self.urls[url]["completed_at"] = timestamp

                # Update header dates if provided
                if header_dates:
                    if header_dates.get("last_modified"):
                        self.urls[url]["header_last_modified"] = header_dates["last_modified"]
                    if header_dates.get("date"):
                        self.urls[url]["header_date"] = header_dates["date"]

                await self._write_state()

    async def set_failed(self, url: str, error: str):
        """
        Mark URL as failed.

        Args:
            url: URL that failed
            error: Error message
        """
        async with self.lock:
            if url in self.urls:
                timestamp = datetime.utcnow().isoformat() + "Z"
                self.urls[url]["status"] = "failed"
                self.urls[url]["error"] = error
                self.urls[url]["completed_at"] = timestamp
                await self._write_state()

    async def get_url_state(self, url: str) -> Optional[Dict[str, Any]]:
        """Get state for a specific URL."""
        async with self.lock:
            return self.urls.get(url, None)

    async def get_all_urls(self) -> Dict[str, Dict[str, Any]]:
        """Get all tracked URLs."""
        async with self.lock:
            return self.urls.copy()

    async def get_stats(self) -> Dict[str, int]:
        """
        Get statistics about URL states.

        Returns:
            Dictionary with counts for each status
        """
        async with self.lock:
            stats = {
                "total": len(self.urls),
                "pending": 0,
                "processing": 0,
                "completed": 0,
                "failed": 0
            }

            for url_data in self.urls.values():
                status = url_data.get("status", "pending")
                if status in stats:
                    stats[status] += 1

            return stats

    async def _write_state(self):
        """
        Write current state to disk.
        Internal method called automatically by update methods.
        """
        try:
            async with aiofiles.open(self.tracking_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(self.urls, indent=2, ensure_ascii=False))
        except Exception as e:
            # Log error but don't fail the job
            print(f"Warning: Failed to write URL tracking state for {self.job_id}: {e}")

    async def read_state(self) -> Dict[str, Dict[str, Any]]:
        """
        Read state from disk.
        Useful for recovery or external monitoring.
        """
        try:
            if self.tracking_file.exists():
                async with aiofiles.open(self.tracking_file, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    self.urls = json.loads(content)
                    return self.urls.copy()
        except Exception as e:
            print(f"Warning: Failed to read URL tracking state for {self.job_id}: {e}")

        return {}

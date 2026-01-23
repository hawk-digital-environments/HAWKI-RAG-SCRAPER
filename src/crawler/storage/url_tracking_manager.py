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
        "url_hash": "SHA256 hash of URL",
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
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
import aiofiles


def generate_url_hash(url: str) -> str:
    """
    Generate SHA256 hash for a URL.

    Args:
        url: URL string to hash

    Returns:
        Hexadecimal SHA256 hash string
    """
    return hashlib.sha256(url.encode('utf-8')).hexdigest()


class URLTrackingManager:
    """
    Manages URL tracking state stored across multiple JSON chunk files.

    Provides methods to:
    - Add URLs from sitemap with lastmod dates
    - Update URL status during processing
    - Add dates from page headers
    - Query URL states

    Storage Strategy:
    - UNIQUE URLs only are stored in chunks of CHUNK_SIZE urls per file
    - Chunk files: urls_chunk_0000.json, urls_chunk_0001.json, etc.
    - Index file: urls_index.json tracks total_entries (including duplicates detected) and unique_urls
    - Duplicates are automatically deduplicated, only first occurrence is kept
    """

    CHUNK_SIZE = 2000  # Unique URLs per chunk file

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
        self.index_file = self.job_dir / "urls_index.json"
        self.chunks_dir = self.job_dir / "url_chunks"
        self.lock = asyncio.Lock()

        # In-memory state - dictionary for unique URLs only
        self.urls: Dict[str, Dict[str, Any]] = {}
        self.total_entries_detected: int = 0  # Track total including duplicates

    async def initialize(self):
        """
        Initialize the tracking system.
        Must be called before using the manager.
        """
        # Resume from existing state if present
        if self.index_file.exists() and self.chunks_dir.exists():
            await self.read_state()
            return

        # Create job directory and chunks directory if needed
        self.job_dir.mkdir(parents=True, exist_ok=True)
        self.chunks_dir.mkdir(exist_ok=True)

        # Initialize index file
        await self._write_index()

    async def add_urls_from_sitemap(self, urls_with_dates: List[tuple]):
        """
        Add multiple URLs discovered from sitemap (deduplicates automatically).

        Args:
            urls_with_dates: List of (url, lastmod_date) tuples
        """
        async with self.lock:
            timestamp = datetime.utcnow().isoformat() + "Z"

            # Count total entries including duplicates
            self.total_entries_detected += len(urls_with_dates)

            # Add only unique URLs
            for url, sitemap_date in urls_with_dates:
                if url not in self.urls:
                    self.urls[url] = {
                        "status": "pending",
                        "url_hash": generate_url_hash(url),
                        "sitemap_date": sitemap_date,
                        "header_last_modified": None,
                        "header_date": None,
                        "page_number": None,
                        "error": None,
                        "discovered_at": timestamp,
                        "completed_at": None
                    }

            await self._write_state()
            num_chunks = (len(self.urls) + self.CHUNK_SIZE - 1) // self.CHUNK_SIZE
            print(f"Stored {len(self.urls)} unique URLs across {num_chunks} chunks (detected {self.total_entries_detected} total entries including duplicates)")

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
                self.total_entries_detected += 1
                self.urls[url] = {
                    "status": "pending",
                    "url_hash": generate_url_hash(url),
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
                self.urls[url]["error"] = None
                self.urls[url]["completed_at"] = None
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
                self.urls[url]["error"] = None

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

    async def set_pending(self, url: str):
        """
        Reset URL status to pending (for retries).

        Args:
            url: URL to reset
        """
        async with self.lock:
            if url in self.urls:
                self.urls[url]["status"] = "pending"
                self.urls[url]["error"] = None
                self.urls[url]["page_number"] = None
                self.urls[url]["completed_at"] = None
                await self._write_state()

    async def get_url_state(self, url: str) -> Optional[Dict[str, Any]]:
        """Get state for a specific URL."""
        async with self.lock:
            return self.urls.get(url, None)

    async def get_all_urls(self) -> Dict[str, Dict[str, Any]]:
        """Get all tracked URLs."""
        async with self.lock:
            return self.urls.copy()

    async def get_urls_by_status(self, statuses: List[str]) -> List[str]:
        """Get URLs with a matching status."""
        async with self.lock:
            return [
                url for url, data in self.urls.items()
                if data.get("status") in statuses
            ]

    async def get_stats(self) -> Dict[str, int]:
        """
        Get statistics about URL states.

        Returns:
            Dictionary with counts for each status
        """
        async with self.lock:
            stats = {
                "total_entries": self.total_entries_detected,
                "unique_urls": len(self.urls),
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

    def _get_chunk_number(self, url_index: int) -> int:
        """Get chunk number for a given URL index."""
        return url_index // self.CHUNK_SIZE

    def _get_chunk_file(self, chunk_num: int) -> Path:
        """Get file path for a specific chunk."""
        return self.chunks_dir / f"urls_chunk_{chunk_num:04d}.json"

    async def _write_index(self):
        """Write index file with metadata about chunks."""
        try:
            index_data = {
                "total_entries": self.total_entries_detected,
                "unique_urls": len(self.urls),
                "chunk_size": self.CHUNK_SIZE,
                "total_chunks": (len(self.urls) + self.CHUNK_SIZE - 1) // self.CHUNK_SIZE if self.urls else 0,
                "last_updated": datetime.utcnow().isoformat() + "Z"
            }
            async with aiofiles.open(self.index_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(index_data, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"Warning: Failed to write URL index for {self.job_id}: {e}")

    async def _write_chunk(self, chunk_num: int, chunk_data: Dict[str, Dict[str, Any]]):
        """Write a specific chunk to disk."""
        try:
            chunk_file = self._get_chunk_file(chunk_num)
            async with aiofiles.open(chunk_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(chunk_data, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"Warning: Failed to write URL chunk {chunk_num} for {self.job_id}: {e}")

    async def _write_state(self):
        """
        Write current state to disk in chunks.
        Internal method called automatically by update methods.

        Writes:
        1. Chunked files (unique URLs only, split into chunks)
        2. Index file (metadata with total_entries including duplicates)
        """
        try:
            # Organize URLs into chunks
            url_list = list(self.urls.items())
            chunks: Dict[int, Dict[str, Dict[str, Any]]] = {}

            for idx, (url, data) in enumerate(url_list):
                chunk_num = self._get_chunk_number(idx)
                if chunk_num not in chunks:
                    chunks[chunk_num] = {}
                chunks[chunk_num][url] = data

            # Write each chunk
            for chunk_num, chunk_data in chunks.items():
                await self._write_chunk(chunk_num, chunk_data)

            # Write index
            await self._write_index()

        except Exception as e:
            # Log error but don't fail the job
            print(f"Warning: Failed to write URL tracking state for {self.job_id}: {e}")

    async def _read_chunk(self, chunk_num: int) -> Dict[str, Dict[str, Any]]:
        """Read a specific chunk from disk."""
        try:
            chunk_file = self._get_chunk_file(chunk_num)
            if chunk_file.exists():
                async with aiofiles.open(chunk_file, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    return json.loads(content)
        except Exception as e:
            print(f"Warning: Failed to read URL chunk {chunk_num} for {self.job_id}: {e}")
        return {}

    async def read_state(self) -> Dict[str, Dict[str, Any]]:
        """
        Read state from disk (all chunks).
        Useful for recovery or external monitoring.
        """
        try:
            # Try reading from chunks
            if self.chunks_dir.exists() and self.index_file.exists():
                async with aiofiles.open(self.index_file, 'r', encoding='utf-8') as f:
                    index_data = json.loads(await f.read())
                    total_chunks = index_data.get('total_chunks', 0)
                    self.total_entries_detected = index_data.get('total_entries', 0)

                # Read all chunks and merge
                all_urls = {}
                for chunk_num in range(total_chunks):
                    chunk_data = await self._read_chunk(chunk_num)
                    all_urls.update(chunk_data)

                self.urls = all_urls
                return self.urls.copy()

        except Exception as e:
            print(f"Warning: Failed to read URL tracking state for {self.job_id}: {e}")

        return {}

"""
StorageManager - File I/O Layer
================================
This class handles all file storage operations for scraped data.
It ensures data is written to the correct job-specific directory structure.

Why this exists:
- Centralizes all file I/O operations
- Ensures consistent directory structure
- Supports streaming to avoid memory issues with large files
- Makes it easy to change storage backend in the future

Directory Structure:
/app/data/jobs/{job_id}/
    ├── job_state.json          # Job metadata (managed by JobStateManager)
    ├── pages/
    │   └── {hash[0]}/{hash[1]}/{hash[2]}/{hash[3]}/{full_hash}/
    │       ├── data.json       # Page metadata
    │       ├── content.md      # Extracted content
    │       ├── images/         # Downloaded images
    │       │   └── image1.jpg
    │       └── files/          # Downloaded PDFs and files
    │           └── file1.pdf
    └── ...

Lifecycle:
- Created when a crawl job starts
- Used throughout scraping to save files
- No explicit cleanup needed (files persist on disk)
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
import aiofiles

from hawki_crawler.crawler.storage.completed_manifest import CompletedUrlManifestStore
from hawki_crawler.crawler.storage.page_output import (
    CONTENT_FILENAME,
    METADATA_FILENAME,
    PAGE_ROOT_DIRNAME,
)


class StorageManager:
    """
    Manages file storage operations for a specific job.

    All file operations go through this class to ensure:
    - Consistent paths
    - Proper error handling
    - Efficient I/O (streaming where applicable)
    """

    def __init__(self, job_id: str, base_path: str = "/app/data/jobs"):
        """
        Initialize storage manager.

        Args:
            job_id: Unique identifier for the job
            base_path: Base directory for job data (default: /app/data/jobs)
        """
        self.job_id = job_id
        self.base_path = Path(base_path)
        self.job_dir = self.base_path / job_id
        self.completed_manifest = CompletedUrlManifestStore(
            job_id=job_id,
            job_dir=self.job_dir,
            get_hash_directory=self.get_hash_directory,
            get_page_directory=self.get_page_directory,
        )

    def get_job_directory(self) -> Path:
        """Get the base directory for this job."""
        return self.job_dir

    def get_completed_urls_manifest_path(self) -> Path:
        """Get the path for the completed-URLs manifest used by downstream RAG pipelines."""
        return self.completed_manifest.get_path()

    def ensure_job_directory(self):
        """Create the job directory if it doesn't exist."""
        self.job_dir.mkdir(parents=True, exist_ok=True)

    def get_hash_directory(self, url_hash: str) -> Path:
        """
        Get the nested directory path for a URL hash.
        Structure: /{hash[0]}/{hash[1]}/{hash[2]}/{hash[3]}/{full_hash}/

        Args:
            url_hash: SHA256 hash of the URL

        Returns:
            Path to hash-based directory
        """
        if len(url_hash) < 4:
            # Fallback for invalid hashes
            return self.job_dir / url_hash

        return self.job_dir / PAGE_ROOT_DIRNAME / url_hash[0] / url_hash[1] / url_hash[2] / url_hash[3] / url_hash

    def get_page_directory(self, page_number: int) -> Path:
        """
        Get the directory path for a specific page.

        Args:
            page_number: Page number (1-indexed)

        Returns:
            Path to page directory
        """
        return self.job_dir / PAGE_ROOT_DIRNAME / f"page_{page_number:05d}"

    def create_hash_directory(
        self,
        url_hash: str,
        create_images_dir: bool = True,
        create_files_dir: bool = False
    ) -> Path:
        """
        Create nested directory structure for a URL hash.

        Args:
            url_hash: SHA256 hash of the URL
            create_images_dir: Whether to create images subdirectory
            create_files_dir: Whether to create files subdirectory

        Returns:
            Path to created hash directory
        """
        hash_dir = self.get_hash_directory(url_hash)
        hash_dir.mkdir(parents=True, exist_ok=True)

        if create_images_dir:
            images_dir = hash_dir / "images"
            images_dir.mkdir(exist_ok=True)

        if create_files_dir:
            files_dir = hash_dir / "files"
            files_dir.mkdir(exist_ok=True)

        return hash_dir

    def create_page_directory(
        self,
        page_number: int,
        create_images_dir: bool = True,
        create_files_dir: bool = False
    ) -> Path:
        """
        DEPRECATED: Use create_hash_directory instead.
        Create directory structure for a specific page.

        Args:
            page_number: Page number (1-indexed)
            create_images_dir: Whether to create images subdirectory
            create_files_dir: Whether to create files subdirectory

        Returns:
            Path to created page directory
        """
        page_dir = self.get_page_directory(page_number)
        page_dir.mkdir(parents=True, exist_ok=True)

        if create_images_dir:
            images_dir = page_dir / "images"
            images_dir.mkdir(exist_ok=True)

        if create_files_dir:
            files_dir = page_dir / "files"
            files_dir.mkdir(exist_ok=True)

        return page_dir

    def get_hash_images_directory(self, url_hash: str) -> Path:
        """Get the images directory for a URL hash."""
        return self.get_hash_directory(url_hash) / "images"

    def get_hash_files_directory(self, url_hash: str) -> Path:
        """Get the files directory for a URL hash."""
        return self.get_hash_directory(url_hash) / "files"

    def get_images_directory(self, page_number: int) -> Path:
        """DEPRECATED: Get the images directory for a specific page."""
        return self.get_page_directory(page_number) / "images"

    def get_files_directory(self, page_number: int) -> Path:
        """DEPRECATED: Get the files directory for a specific page."""
        return self.get_page_directory(page_number) / "files"

    async def save_hash_json(self, url_hash: str, data: Dict[str, Any]):
        """
        Save page metadata as JSON using hash-based directory.

        Args:
            url_hash: SHA256 hash of the URL
            data: Dictionary to save as JSON
        """
        hash_dir = self.get_hash_directory(url_hash)
        json_file = hash_dir / METADATA_FILENAME

        async with aiofiles.open(json_file, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False))

    async def save_hash_content(self, url_hash: str, content: str):
        """
        Save page content as markdown using hash-based directory.

        Args:
            url_hash: SHA256 hash of the URL
            content: Content to save
        """
        hash_dir = self.get_hash_directory(url_hash)
        content_file = hash_dir / CONTENT_FILENAME

        async with aiofiles.open(content_file, 'w', encoding='utf-8') as f:
            await f.write(content if content else "")

    async def upsert_completed_url_record(
        self,
        metadata: Dict[str, Any],
        *,
        url_hash: Optional[str] = None,
        page_number: Optional[int] = None
    ) -> None:
        """
        Update a job-level manifest of successfully saved URLs for retrieval pipelines.

        The manifest intentionally denormalizes the most useful page metadata so downstream
        conversion/ingestion jobs can enumerate completed pages without re-scanning the
        page directory tree.
        """
        await self.completed_manifest.upsert_record(
            metadata,
            url_hash=url_hash,
            page_number=page_number,
        )

    async def save_page_json(self, page_number: int, data: Dict[str, Any]):
        """
        DEPRECATED: Use save_hash_json instead.
        Save page metadata as JSON.

        Args:
            page_number: Page number (1-indexed)
            data: Dictionary to save as JSON
        """
        page_dir = self.get_page_directory(page_number)
        json_file = page_dir / METADATA_FILENAME

        async with aiofiles.open(json_file, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False))

    async def save_page_content(self, page_number: int, content: str):
        """
        DEPRECATED: Use save_hash_content instead.
        Save page content as markdown.

        Args:
            page_number: Page number (1-indexed)
            content: Content to save
        """
        page_dir = self.get_page_directory(page_number)
        content_file = page_dir / CONTENT_FILENAME

        async with aiofiles.open(content_file, 'w', encoding='utf-8') as f:
            await f.write(content if content else "")

    async def save_hash_image(self, url_hash: str, filename: str, image_data: bytes) -> str:
        """
        Save image file using hash-based directory.

        Args:
            url_hash: SHA256 hash of the URL
            filename: Image filename
            image_data: Raw image bytes

        Returns:
            Saved filename
        """
        images_dir = self.get_hash_images_directory(url_hash)
        filepath = images_dir / filename

        async with aiofiles.open(filepath, 'wb') as f:
            await f.write(image_data)

        return filename

    async def save_hash_pdf(self, url_hash: str, filename: str, pdf_data: bytes) -> str:
        """
        Save PDF file using hash-based directory.

        Args:
            url_hash: SHA256 hash of the URL
            filename: PDF filename
            pdf_data: Raw PDF bytes

        Returns:
            Saved filename
        """
        files_dir = self.get_hash_files_directory(url_hash)
        files_dir.mkdir(parents=True, exist_ok=True)
        filepath = files_dir / filename

        async with aiofiles.open(filepath, 'wb') as f:
            await f.write(pdf_data)

        return filename

    async def save_image(self, page_number: int, filename: str, image_data: bytes) -> str:
        """
        DEPRECATED: Use save_hash_image instead.
        Save image file.

        Args:
            page_number: Page number (1-indexed)
            filename: Image filename
            image_data: Raw image bytes

        Returns:
            Saved filename
        """
        images_dir = self.get_images_directory(page_number)
        filepath = images_dir / filename

        async with aiofiles.open(filepath, 'wb') as f:
            await f.write(image_data)

        return filename

    async def save_pdf(self, page_number: int, filename: str, pdf_data: bytes) -> str:
        """
        DEPRECATED: Use save_hash_pdf instead.
        Save PDF file.

        Args:
            page_number: Page number (1-indexed)
            filename: PDF filename
            pdf_data: Raw PDF bytes

        Returns:
            Saved filename
        """
        files_dir = self.get_files_directory(page_number)
        files_dir.mkdir(parents=True, exist_ok=True)
        filepath = files_dir / filename

        async with aiofiles.open(filepath, 'wb') as f:
            await f.write(pdf_data)

        return filename

    def list_files(self, relative: bool = True) -> List[str]:
        """
        List all files in the job directory.

        Args:
            relative: If True, return paths relative to job directory

        Returns:
            List of file paths
        """
        files = []

        if not self.job_dir.exists():
            return files

        for root, dirs, filenames in os.walk(self.job_dir):
            for filename in filenames:
                filepath = Path(root) / filename

                if relative:
                    # Return path relative to job directory
                    rel_path = filepath.relative_to(self.job_dir)
                    files.append(str(rel_path))
                else:
                    files.append(str(filepath))

        return sorted(files)

    def get_file_path(self, relative_path: str) -> Optional[Path]:
        """
        Get absolute path for a file in the job directory.

        Args:
            relative_path: Path relative to job directory

        Returns:
            Absolute Path object if file exists, None otherwise
        """
        filepath = self.job_dir / relative_path

        # Security check: ensure the path is within job directory
        try:
            filepath = filepath.resolve()
            if not str(filepath).startswith(str(self.job_dir.resolve())):
                return None
        except Exception:
            return None

        if filepath.exists() and filepath.is_file():
            return filepath

        return None

    def get_file_info(self, relative_path: str) -> Optional[Dict[str, Any]]:
        """
        Get file information.

        Args:
            relative_path: Path relative to job directory

        Returns:
            Dictionary with file info or None if file doesn't exist
        """
        filepath = self.get_file_path(relative_path)

        if not filepath:
            return None

        stat = filepath.stat()

        return {
            "name": filepath.name,
            "path": relative_path,
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "type": self._get_file_type(filepath)
        }

    def _get_file_type(self, filepath: Path) -> str:
        """Determine file type from extension."""
        suffix = filepath.suffix.lower()

        type_map = {
            ".json": "application/json",
            ".md": "text/markdown",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".txt": "text/plain",
            ".html": "text/html",
            ".pdf": "application/pdf"
        }

        return type_map.get(suffix, "application/octet-stream")

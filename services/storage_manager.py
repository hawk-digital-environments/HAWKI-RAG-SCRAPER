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
    ├── page_00001/
    │   ├── data.json           # Page metadata
    │   ├── content.md          # Extracted content
    │   └── images/             # Downloaded images
    │       └── image1.jpg
    ├── page_00002/
    │   └── ...
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

    def get_job_directory(self) -> Path:
        """Get the base directory for this job."""
        return self.job_dir

    def ensure_job_directory(self):
        """Create the job directory if it doesn't exist."""
        self.job_dir.mkdir(parents=True, exist_ok=True)

    def get_page_directory(self, page_number: int) -> Path:
        """
        Get the directory path for a specific page.

        Args:
            page_number: Page number (1-indexed)

        Returns:
            Path to page directory
        """
        return self.job_dir / f"page_{page_number:05d}"

    def create_page_directory(self, page_number: int, create_images_dir: bool = True) -> Path:
        """
        Create directory structure for a specific page.

        Args:
            page_number: Page number (1-indexed)
            create_images_dir: Whether to create images subdirectory

        Returns:
            Path to created page directory
        """
        page_dir = self.get_page_directory(page_number)
        page_dir.mkdir(parents=True, exist_ok=True)

        if create_images_dir:
            images_dir = page_dir / "images"
            images_dir.mkdir(exist_ok=True)

        return page_dir

    def get_images_directory(self, page_number: int) -> Path:
        """Get the images directory for a specific page."""
        return self.get_page_directory(page_number) / "images"

    async def save_page_json(self, page_number: int, data: Dict[str, Any]):
        """
        Save page metadata as JSON.

        Args:
            page_number: Page number (1-indexed)
            data: Dictionary to save as JSON
        """
        page_dir = self.get_page_directory(page_number)
        json_file = page_dir / "data.json"

        async with aiofiles.open(json_file, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(data, indent=2, ensure_ascii=False))

    async def save_page_content(self, page_number: int, content: str):
        """
        Save page content as markdown.

        Args:
            page_number: Page number (1-indexed)
            content: Content to save
        """
        page_dir = self.get_page_directory(page_number)
        content_file = page_dir / "content.md"

        async with aiofiles.open(content_file, 'w', encoding='utf-8') as f:
            await f.write(content if content else "")

    async def save_image(self, page_number: int, filename: str, image_data: bytes) -> str:
        """
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
            ".html": "text/html"
        }

        return type_map.get(suffix, "application/octet-stream")

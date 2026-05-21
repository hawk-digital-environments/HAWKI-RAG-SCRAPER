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

from pathlib import Path
from typing import Dict, Any, Optional, List

from hawki_crawler.crawler.storage.asset_store import AssetStore
from hawki_crawler.crawler.storage.completed_manifest import CompletedUrlManifestStore
from hawki_crawler.crawler.storage.file_browser import FileBrowser
from hawki_crawler.crawler.storage.page_store import PageStore


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
        self.page_store = PageStore(job_dir=self.job_dir)
        self.asset_store = AssetStore(
            get_hash_directory=self.get_hash_directory,
            get_page_directory=self.get_page_directory,
        )
        self.file_browser = FileBrowser(job_dir=self.job_dir)
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
        return self.page_store.get_hash_directory(url_hash)

    def get_page_directory(self, page_number: int) -> Path:
        """
        Get the directory path for a specific page.

        Args:
            page_number: Page number (1-indexed)

        Returns:
            Path to page directory
        """
        return self.page_store.get_page_directory(page_number)

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
        return self.page_store.create_hash_directory(
            url_hash,
            create_images_dir=create_images_dir,
            create_files_dir=create_files_dir,
        )

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
        return self.page_store.create_page_directory(
            page_number,
            create_images_dir=create_images_dir,
            create_files_dir=create_files_dir,
        )

    def get_hash_images_directory(self, url_hash: str) -> Path:
        """Get the images directory for a URL hash."""
        return self.asset_store.get_hash_images_directory(url_hash)

    def get_hash_files_directory(self, url_hash: str) -> Path:
        """Get the files directory for a URL hash."""
        return self.asset_store.get_hash_files_directory(url_hash)

    def get_images_directory(self, page_number: int) -> Path:
        """DEPRECATED: Get the images directory for a specific page."""
        return self.asset_store.get_images_directory(page_number)

    def get_files_directory(self, page_number: int) -> Path:
        """DEPRECATED: Get the files directory for a specific page."""
        return self.asset_store.get_files_directory(page_number)

    async def save_hash_json(self, url_hash: str, data: Dict[str, Any]):
        """
        Save page metadata as JSON using hash-based directory.

        Args:
            url_hash: SHA256 hash of the URL
            data: Dictionary to save as JSON
        """
        await self.page_store.save_hash_json(url_hash, data)

    async def save_hash_content(self, url_hash: str, content: str):
        """
        Save page content as markdown using hash-based directory.

        Args:
            url_hash: SHA256 hash of the URL
            content: Content to save
        """
        await self.page_store.save_hash_content(url_hash, content)

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
        await self.page_store.save_page_json(page_number, data)

    async def save_page_content(self, page_number: int, content: str):
        """
        DEPRECATED: Use save_hash_content instead.
        Save page content as markdown.

        Args:
            page_number: Page number (1-indexed)
            content: Content to save
        """
        await self.page_store.save_page_content(page_number, content)

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
        return await self.asset_store.save_hash_image(url_hash, filename, image_data)

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
        return await self.asset_store.save_hash_pdf(url_hash, filename, pdf_data)

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
        return await self.asset_store.save_image(page_number, filename, image_data)

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
        return await self.asset_store.save_pdf(page_number, filename, pdf_data)

    def list_files(self, relative: bool = True) -> List[str]:
        """
        List all files in the job directory.

        Args:
            relative: If True, return paths relative to job directory

        Returns:
            List of file paths
        """
        return self.file_browser.list_files(relative=relative)

    def get_file_path(self, relative_path: str) -> Optional[Path]:
        """
        Get absolute path for a file in the job directory.

        Args:
            relative_path: Path relative to job directory

        Returns:
            Absolute Path object if file exists, None otherwise
        """
        return self.file_browser.get_file_path(relative_path)

    def get_file_info(self, relative_path: str) -> Optional[Dict[str, Any]]:
        """
        Get file information.

        Args:
            relative_path: Path relative to job directory

        Returns:
            Dictionary with file info or None if file doesn't exist
        """
        return self.file_browser.get_file_info(relative_path)

    def _get_file_type(self, filepath: Path) -> str:
        """Determine file type from extension."""
        return self.file_browser.get_file_type(filepath)

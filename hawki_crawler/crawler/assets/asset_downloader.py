import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import aiohttp

from hawki_crawler.crawler.assets.asset_policy import AssetPolicy
from hawki_crawler.crawler.assets.asset_saver import AssetSaver
from hawki_crawler.crawler.assets.file_downloader import FileDownloader
from hawki_crawler.crawler.assets.file_event_notifier import FileEventNotifier
from hawki_crawler.crawler.assets.image_downloader import ImageDownloader
from hawki_crawler.crawler.assets.resource_detector import FetchHeadCallable, ResourceDetector


class AssetDownloader:
    """Network download behavior for images, PDFs, and supported files."""

    def __init__(
        self,
        *,
        rate_limiter: Any,
        headers: Dict[str, str],
        http_session: Optional[aiohttp.ClientSession],
        asset_saver: AssetSaver,
        file_event_publisher: Optional[Any] = None,
        job_id: Optional[str] = None,
        logger: Optional[Any] = None,
        policy: Optional[AssetPolicy] = None,
        fetch_head: Optional[FetchHeadCallable] = None,
    ) -> None:
        self.rate_limiter = rate_limiter
        self.headers = headers
        self.http_session = http_session
        self.asset_saver = asset_saver
        self.file_event_publisher = file_event_publisher
        self.job_id = job_id
        self.logger = logger or logging.getLogger("crawler")
        self.policy = policy or AssetPolicy()
        self._fetch_head_override = fetch_head

    def _image_downloader(self) -> ImageDownloader:
        return ImageDownloader(rate_limiter=self.rate_limiter, logger=self.logger)

    def _file_event_notifier(self) -> FileEventNotifier:
        return FileEventNotifier(
            file_event_publisher=self.file_event_publisher,
            job_id=self.job_id,
            logger=self.logger,
        )

    def _resource_detector(self) -> ResourceDetector:
        return ResourceDetector(
            rate_limiter=self.rate_limiter,
            http_session=self.http_session,
            logger=self.logger,
            policy=self.policy,
            fetch_head=self._fetch_head_override,
        )

    def _file_downloader(self) -> FileDownloader:
        return FileDownloader(
            rate_limiter=self.rate_limiter,
            headers=self.headers,
            asset_saver=self.asset_saver,
            file_event_notifier=self._file_event_notifier(),
            logger=self.logger,
            policy=self.policy,
        )

    async def publish_saved_file_event(
        self,
        *,
        file_url: str,
        page_url: Optional[str],
        file_entry: Dict[str, str],
    ) -> None:
        await self._file_event_notifier().publish_saved_file_event(
            file_url=file_url,
            page_url=page_url,
            file_entry=file_entry,
        )

    async def download_image(
        self,
        image_url: str,
        session: aiohttp.ClientSession,
        images_dir: Path,
    ) -> Optional[str]:
        """Download an image and save it to the images directory."""
        return await self._image_downloader().download_image(image_url, session, images_dir)

    async def fetch_head(self, url: str) -> Tuple[Optional[int], Dict[str, str]]:
        """Fetch HEAD request for a URL."""
        return await self._resource_detector().fetch_head(url)

    async def _resolve_head_headers(self, url: str, head_headers: Optional[Dict[str, str]]) -> Dict[str, str]:
        return await self._resource_detector().resolve_head_headers(url, head_headers)

    async def is_pdf_resource(
        self,
        url: str,
        head_status: Optional[int] = None,
        head_headers: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Check if a URL points directly to a PDF."""
        return await self._resource_detector().is_pdf_resource(
            url,
            head_status=head_status,
            head_headers=head_headers,
        )

    async def is_file_resource(
        self,
        url: str,
        head_status: Optional[int] = None,
        head_headers: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Check if a URL points directly to a non-PDF file."""
        return await self._resource_detector().is_file_resource(
            url,
            head_status=head_status,
            head_headers=head_headers,
        )

    async def fetch_and_save_pdf(
        self,
        pdf_url: str,
        page_number: int,
        session: Optional[aiohttp.ClientSession] = None,
        url_hash: Optional[str] = None,
        page_url: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        """Download a PDF and save it to the files directory."""
        return await self._file_downloader().fetch_and_save_pdf(
            pdf_url,
            page_number,
            session=session,
            url_hash=url_hash,
            page_url=page_url,
        )

    async def fetch_and_save_file(
        self,
        file_url: str,
        page_number: int,
        session: Optional[aiohttp.ClientSession] = None,
        url_hash: Optional[str] = None,
        page_url: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        """Download a non-PDF file and save it to the files directory."""
        return await self._file_downloader().fetch_and_save_file(
            file_url,
            page_number,
            session=session,
            url_hash=url_hash,
            page_url=page_url,
        )

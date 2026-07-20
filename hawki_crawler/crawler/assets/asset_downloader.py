import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import aiohttp

from hawki_crawler.crawler.assets.asset_saver import AssetSaver
from hawki_crawler.crawler.assets.file_downloader import FileDownloader
from hawki_crawler.crawler.assets.image_downloader import ImageDownloader
from hawki_crawler.crawler.parsing.resource_parser import ResourceParser
from hawki_crawler.crawler.policies.resource_policy import ResourcePolicy


class AssetDownloader:
    """Network download behavior for images, PDFs, and supported files."""

    def __init__(
        self,
        *,
        rate_limiter: Any,
        headers: Dict[str, str],
        http_session: Optional[aiohttp.ClientSession],
        asset_saver: AssetSaver,
        logger: Optional[Any] = None,
        resource_policy: Optional[ResourcePolicy] = None,
        resource_parser: Optional[ResourceParser] = None,
        policy: Optional[ResourcePolicy] = None,
    ) -> None:
        self.rate_limiter = rate_limiter
        self.headers = headers
        self.http_session = http_session
        self.asset_saver = asset_saver
        self.logger = logger or logging.getLogger("crawler")
        self.resource_policy = resource_policy or policy or ResourcePolicy()
        self.resource_parser = resource_parser or ResourceParser(self.resource_policy)

    def _image_downloader(self) -> ImageDownloader:
        return ImageDownloader(rate_limiter=self.rate_limiter, logger=self.logger)

    def _file_downloader(self) -> FileDownloader:
        return FileDownloader(
            rate_limiter=self.rate_limiter,
            headers=self.headers,
            asset_saver=self.asset_saver,
            logger=self.logger,
            resource_policy=self.resource_policy,
            resource_parser=self.resource_parser,
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
        await self.rate_limiter.acquire()
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with self.http_session.head(
                url,
                allow_redirects=True,
                timeout=timeout,
            ) as response:
                headers = {key.lower(): value for key, value in response.headers.items()}
                return response.status, headers
        except Exception as exc:
            self.logger.warning("HEAD request failed for %s: %s", url, exc)
            return None, {}

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

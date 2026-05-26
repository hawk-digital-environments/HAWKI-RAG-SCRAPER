import logging
from pathlib import Path
from typing import Dict, Optional, List, Tuple, TYPE_CHECKING

import aiohttp

from hawki_crawler.crawler.assets.asset_downloader import AssetDownloader
from hawki_crawler.crawler.assets.asset_saver import AssetSaver
from hawki_crawler.crawler.assets.asset_policy import AssetPolicy

if TYPE_CHECKING:
    from hawki_crawler.crawler.core.protocols import ServiceParseAssetsMixinProtocol


class ServiceParseAssetsMixin:
    """Compatibility mixin that delegates asset downloads to AssetDownloader."""

    def _asset_policy(self) -> AssetPolicy:
        return AssetPolicy()

    def _asset_saver(self: "ServiceParseAssetsMixinProtocol") -> AssetSaver:
        return AssetSaver(
            storage_manager=getattr(self, "storage_manager", None),
            create_page_directory=self.create_page_directory,
            skip_images=getattr(self.config, "skip_images", False),
        )

    def _asset_logger(self: "ServiceParseAssetsMixinProtocol"):
        return getattr(self, "job_logger", logging.getLogger("crawler"))

    def _asset_downloader(self: "ServiceParseAssetsMixinProtocol", *, fetch_head=None) -> AssetDownloader:
        return AssetDownloader(
            rate_limiter=self.rate_limiter,
            headers=self.headers,
            http_session=getattr(self, "http_session", None),
            asset_saver=self._asset_saver(),
            file_event_publisher=getattr(self, "file_event_publisher", None),
            job_id=getattr(self, "job_id", None),
            logger=self._asset_logger(),
            policy=self._asset_policy(),
            fetch_head=fetch_head,
        )

    async def _publish_saved_file_event(
        self: "ServiceParseAssetsMixinProtocol",
        *,
        file_url: str,
        page_url: Optional[str],
        file_entry: Dict[str, str],
    ) -> None:
        await self._asset_downloader().publish_saved_file_event(
            file_url=file_url,
            page_url=page_url,
            file_entry=file_entry,
        )

    async def download_image(
        self: "ServiceParseAssetsMixinProtocol",
        image_url: str,
        session: aiohttp.ClientSession,
        images_dir: Path
    ) -> Optional[str]:
        """Download an image and save it to the images directory."""
        return await self._asset_downloader().download_image(image_url, session, images_dir)

    def extract_pdf_links(self, html_content: str, base_url: str) -> List[str]:
        """Extract PDF links from HTML content"""
        return self._asset_policy().extract_pdf_links(html_content, base_url)

    def extract_file_links(self, html_content: str, base_url: str) -> List[str]:
        """Extract non-PDF file links from HTML content."""
        return self._asset_policy().extract_file_links(html_content, base_url)

    def _should_skip_file_download(
        self,
        url: str,
        filename: Optional[str],
        content_type: str
    ) -> bool:
        """Skip downloads that resolve to disallowed or extension-less files."""
        return self._asset_policy().should_skip_file_download(url, filename, content_type)

    async def fetch_head(self: "ServiceParseAssetsMixinProtocol", url: str) -> Tuple[Optional[int], Dict[str, str]]:
        """Fetch HEAD request for a URL."""
        return await self._asset_downloader().fetch_head(url)

    async def is_pdf_resource(
        self: "ServiceParseAssetsMixinProtocol",
        url: str,
        head_status: Optional[int] = None,
        head_headers: Optional[Dict[str, str]] = None
    ) -> bool:
        """Check if a URL points directly to a PDF."""
        return await self._asset_downloader(fetch_head=self.fetch_head).is_pdf_resource(
            url,
            head_status=head_status,
            head_headers=head_headers,
        )

    async def is_file_resource(
        self: "ServiceParseAssetsMixinProtocol",
        url: str,
        head_status: Optional[int] = None,
        head_headers: Optional[Dict[str, str]] = None
    ) -> bool:
        """Check if a URL points directly to a non-PDF file."""
        return await self._asset_downloader(fetch_head=self.fetch_head).is_file_resource(
            url,
            head_status=head_status,
            head_headers=head_headers,
        )

    def _filename_from_content_disposition(self, header_value: str) -> Optional[str]:
        return self._asset_policy().filename_from_content_disposition(header_value)

    async def fetch_and_save_pdf(
        self: "ServiceParseAssetsMixinProtocol",
        pdf_url: str,
        page_number: int,
        session: Optional[aiohttp.ClientSession] = None,
        url_hash: Optional[str] = None,
        page_url: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        """Download a PDF and save it to the files directory."""
        return await self._asset_downloader().fetch_and_save_pdf(
            pdf_url,
            page_number,
            session=session,
            url_hash=url_hash,
            page_url=page_url,
        )

    async def fetch_and_save_file(
        self: "ServiceParseAssetsMixinProtocol",
        file_url: str,
        page_number: int,
        session: Optional[aiohttp.ClientSession] = None,
        url_hash: Optional[str] = None,
        page_url: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        """Download a non-PDF file and save it to the files directory."""
        return await self._asset_downloader().fetch_and_save_file(
            file_url,
            page_number,
            session=session,
            url_hash=url_hash,
            page_url=page_url,
        )

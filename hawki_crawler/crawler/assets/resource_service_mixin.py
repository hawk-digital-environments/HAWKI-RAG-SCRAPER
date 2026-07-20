import logging
from pathlib import Path
from typing import Dict, Optional, Tuple, TYPE_CHECKING

import aiohttp

from hawki_crawler.crawler.assets.asset_downloader import AssetDownloader
from hawki_crawler.crawler.assets.asset_saver import AssetSaver
from hawki_crawler.crawler.parsing.resource_parser import ResourceParser
from hawki_crawler.crawler.policies.resource_policy import (
    ResourcePolicy,
    ResourcePolicyClientMixin,
)

if TYPE_CHECKING:
    from hawki_crawler.crawler.core.protocols import ServiceParseResourceMixinProtocol


class ServiceParseResourceMixin(ResourcePolicyClientMixin):
    """Delegate resource detection and downloads to focused services."""

    def _init_resource_services(self) -> None:
        """Attach the shared resource classification and parsing services."""
        self.resource_policy = ResourcePolicy(
            site_profile=self.site_profile,
            crawl_host=getattr(self, "crawl_host", None),
        )
        self._resource_parser = ResourceParser(self.resource_policy)

    def _resource_saver(self: "ServiceParseResourceMixinProtocol") -> AssetSaver:
        return AssetSaver(
            storage_manager=getattr(self, "storage_manager", None),
            create_page_directory=self.create_page_directory,
            skip_images=getattr(self.config, "skip_images", False),
        )

    def _resource_logger(self: "ServiceParseResourceMixinProtocol"):
        return getattr(self, "job_logger", logging.getLogger("crawler"))

    def _resource_downloader(
        self: "ServiceParseResourceMixinProtocol",
    ) -> AssetDownloader:
        return AssetDownloader(
            rate_limiter=self.rate_limiter,
            headers=self.headers,
            http_session=getattr(self, "http_session", None),
            asset_saver=self._resource_saver(),
            logger=self._resource_logger(),
            resource_policy=self.resource_policy,
            resource_parser=self._resource_parser,
        )

    async def download_image(
        self: "ServiceParseResourceMixinProtocol",
        image_url: str,
        session: aiohttp.ClientSession,
        images_dir: Path,
    ) -> Optional[str]:
        """Download an image and save it to the images directory."""
        return await self._resource_downloader().download_image(image_url, session, images_dir)

    async def fetch_head(
        self: "ServiceParseResourceMixinProtocol",
        url: str,
    ) -> Tuple[Optional[int], Dict[str, str]]:
        """Fetch HEAD request for a URL."""
        return await self._resource_downloader().fetch_head(url)

    async def fetch_and_save_pdf(
        self: "ServiceParseResourceMixinProtocol",
        pdf_url: str,
        page_number: int,
        session: Optional[aiohttp.ClientSession] = None,
        url_hash: Optional[str] = None,
        page_url: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        """Download a PDF and save it to the files directory."""
        return await self._resource_downloader().fetch_and_save_pdf(
            pdf_url,
            page_number,
            session=session,
            url_hash=url_hash,
            page_url=page_url,
        )

    async def fetch_and_save_file(
        self: "ServiceParseResourceMixinProtocol",
        file_url: str,
        page_number: int,
        session: Optional[aiohttp.ClientSession] = None,
        url_hash: Optional[str] = None,
        page_url: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        """Download a non-PDF file and save it to the files directory."""
        return await self._resource_downloader().fetch_and_save_file(
            file_url,
            page_number,
            session=session,
            url_hash=url_hash,
            page_url=page_url,
        )

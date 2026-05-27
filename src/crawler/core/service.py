from pathlib import Path

from hawki_crawler.crawler.assets.asset_service_mixin import ServiceParseAssetsMixin
from hawki_crawler.crawler.core.execution.execution_mixin import ServiceCrawlExecutionMixin
from hawki_crawler.crawler.core.runtime.init_mixin import ServiceInitMixin
from hawki_crawler.crawler.core.runtime.runtime_mixin import ServiceCrawlRuntimeMixin
from hawki_crawler.crawler.parsing.content_mixin import ServiceParseContentMixin
from hawki_crawler.crawler.sitemap.sitemap_mixin import ServiceSitemapMixin


class CrawlerService(
    ServiceInitMixin,
    ServiceSitemapMixin,
    ServiceParseAssetsMixin,
    ServiceParseContentMixin,
    ServiceCrawlRuntimeMixin,
    ServiceCrawlExecutionMixin
):
    """Main crawler service handling all crawling operations."""

    async def setup_directories(self) -> None:
        await self.runtime_storage.setup_directories()

    async def create_page_directory(
        self,
        page_number: int,
        create_files_dir: bool = False,
    ) -> Path:
        return await self.runtime_storage.create_page_directory(
            page_number,
            create_files_dir=create_files_dir,
        )

from typing import Any, Dict, Optional, List, TYPE_CHECKING

from bs4 import BeautifulSoup

from hawki_crawler.crawler.parsing.page_extractor import PageExtractor

if TYPE_CHECKING:
    from hawki_crawler.crawler.core.protocols import ServiceParseContentMixinProtocol


class ServiceParseContentMixin:
    """Compatibility mixin that delegates page extraction to PageExtractor."""

    def _page_extractor(self: "ServiceParseContentMixinProtocol") -> PageExtractor:
        return PageExtractor(
            config=self.config,
            site_profile=getattr(self, "site_profile", {}) or {},
            progress_tracker=getattr(self, "progress_tracker", None),
            url_tracking_manager=getattr(self, "url_tracking_manager", None),
            storage_manager=getattr(self, "storage_manager", None),
            headers=getattr(self, "headers", {}) or {},
            job_logger=self.job_logger,
            first_sitemap_entry=self.first_sitemap_entry,
            detect_language=self.detect_language,
            get_sitemap_date=self.get_sitemap_date,
            parse_http_date=self.parse_http_date,
            create_page_directory=self.create_page_directory,
            download_image=self.download_image,
        )

    def _site_profile_extractors(self: "ServiceParseContentMixinProtocol") -> Dict[str, List[str]]:
        return self._page_extractor().site_profile_extractors()

    def _extract_tags(self, soup: BeautifulSoup, selectors: Optional[List[str]] = None) -> List[str]:
        return self._page_extractor().extract_tags(soup, selectors)

    def _fix_mojibake(self, text: str) -> str:
        return self._page_extractor().fix_mojibake(text)

    def _extract_result_markdown(self, result: Any) -> str:
        return self._page_extractor().extract_result_markdown(result)

    def _clean_markdown_output(
        self: "ServiceParseContentMixinProtocol",
        markdown: str,
        noise_phrases: List[str],
    ) -> tuple[str, List[str]]:
        return self._page_extractor().clean_markdown_output(markdown, noise_phrases)

    async def extract_page_data(
        self: "ServiceParseContentMixinProtocol",
        url: str,
        page_number: int,
        *,
        crawl_result: Any,
        head_headers: Optional[Dict[str, str]] = None,
        head_status: Optional[int] = None,
        depth: int = 0,
        source_type: str = "seed",
        url_hash: Optional[str] = None,
    ) -> Optional[Dict]:
        return await self._page_extractor().extract_page_data(
            url,
            page_number,
            crawl_result=crawl_result,
            head_headers=head_headers,
            head_status=head_status,
            depth=depth,
            source_type=source_type,
            url_hash=url_hash,
        )

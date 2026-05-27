from typing import Dict, Optional, TYPE_CHECKING

from bs4 import BeautifulSoup

from hawki_crawler.crawler.parsing.date_language import DateLanguageService

if TYPE_CHECKING:
    from hawki_crawler.crawler.core.protocols import ServiceDateLangMixinProtocol


class ServiceDateLangMixin:
    """Compatibility mixin that delegates date/language parsing."""

    def _date_language_service(self: "ServiceDateLangMixinProtocol") -> DateLanguageService:
        return DateLanguageService(
            sitemap_lookup=getattr(self, "lookup_sitemap_entry", None),
        )

    def parse_date_string(self: "ServiceDateLangMixinProtocol", date_str: str) -> Optional[str]:
        return self._date_language_service().parse_date_string(date_str)

    def extract_dates(
        self: "ServiceDateLangMixinProtocol",
        html_content: str,
        soup: BeautifulSoup,
    ) -> Dict[str, Optional[str]]:
        return self._date_language_service().extract_dates(html_content, soup)

    def detect_language(
        self: "ServiceDateLangMixinProtocol",
        html_content: Optional[str],
        head_headers: Optional[Dict[str, str]],
        url: Optional[str] = None,
        sitemap_entry: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        return self._date_language_service().detect_language(
            html_content,
            head_headers,
            url=url,
            sitemap_entry=sitemap_entry,
        )

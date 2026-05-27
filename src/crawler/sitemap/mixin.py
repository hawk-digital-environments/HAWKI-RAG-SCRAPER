import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, List, TYPE_CHECKING

from hawki_crawler.crawler.sitemap.parser import SitemapParser
from hawki_crawler.crawler.sitemap.scraper import SitemapScraper
from hawki_crawler.crawler.sitemap.service import SitemapService

if TYPE_CHECKING:
    from hawki_crawler.crawler.core.protocols import ServiceSitemapMixinProtocol

LOGGER = logging.getLogger("crawler.sitemap")


class ServiceSitemapMixin:
    def _sitemap_service(self: "ServiceSitemapMixinProtocol") -> SitemapService:
        return SitemapService(
            sitemap_map=getattr(self, "sitemap_map", {}) or {},
            is_forbidden_url=self.is_forbidden_url,
            is_discovery_url_allowed=self.is_discovery_url_allowed,
            normalize_url=self.normalize_url,
        )

    def _sitemap_parser(self: "ServiceSitemapMixinProtocol") -> SitemapParser:
        return SitemapParser(
            headers=getattr(self, "headers", {}) or {},
            sitemap_map=self.sitemap_map,
            sitemap_lastmod=self.sitemap_lastmod,
            is_forbidden_url=self.is_forbidden_url,
            normalize_url_key=self._normalize_url_key,
            normalize_sitemap_meta=self._normalize_sitemap_meta,
            get_sitemap_date=self.get_sitemap_date,
            url_tracking_manager=getattr(self, "url_tracking_manager", None),
            job_id=getattr(self, "job_id", None),
        )

    def _normalize_url_key(self, url: str) -> Optional[str]:
        return self._sitemap_service().normalize_url_key(url)

    def _normalize_sitemap_meta(self, meta: Any) -> Dict[str, Any]:
        return self._sitemap_service().normalize_sitemap_meta(meta)

    def get_sitemap_date(self, entry: Optional[Dict[str, Any]]) -> Optional[str]:
        return self._sitemap_service().get_sitemap_date(entry)

    def load_sitemap_map(self: "ServiceSitemapMixinProtocol", path: str) -> Dict[str, Dict[str, str]]:
        return self._sitemap_service().load_sitemap_map(path)

    def load_sitemap_urls(self: "ServiceSitemapMixinProtocol", path: str) -> List[str]:
        return self._sitemap_service().load_sitemap_urls(path)

    def lookup_sitemap_entry(self: "ServiceSitemapMixinProtocol", url: str) -> Optional[Dict[str, str]]:
        return self._sitemap_service().lookup_sitemap_entry(url)

    def first_sitemap_entry(self: "ServiceSitemapMixinProtocol", *urls: str) -> Optional[Dict[str, str]]:
        return self._sitemap_service().first_sitemap_entry(*urls)

    def parse_http_date(self, date_str: Optional[str]) -> Optional[str]:
        return self._sitemap_service().parse_http_date(date_str)

    async def run_sitemap_scrape(self: "ServiceSitemapMixinProtocol"):
        """Optionally scrape the sitemap JSON before crawling."""
        if not getattr(self.config, "sitemap", False):
            return
        sitemap_profile = (getattr(self, "site_profile", {}) or {}).get("sitemap", {})
        base_url = self.sitemap_base or sitemap_profile.get("base_url")
        if not base_url:
            return
        output_path = Path(self.sitemap_path)
        start_page = self.config.sitemap_start_page or int(os.getenv("SITEMAP_START", str(sitemap_profile.get("start_page", "1"))))
        max_pages = self.config.sitemap_pages or int(os.getenv("SITEMAP_PAGES", str(sitemap_profile.get("pages", "6"))))

        try:
            scraper = SitemapScraper(
                base_url=base_url,
                output_path=str(output_path),
                start_page=start_page,
                max_pages=max_pages,
                profile=(getattr(self, "site_profile", {}) or {}),
            )
            await scraper.scrape()
            self.sitemap_map = self.load_sitemap_map(str(output_path))
            self.sitemap_urls = self.load_sitemap_urls(str(output_path))
        except Exception as e:
            LOGGER.error("Error scraping sitemap: %s", e, extra={"job_id": getattr(self, "job_id", None)})

    async def is_sitemap(self, url: str) -> bool:
        return await self._sitemap_parser().is_sitemap(url)

    async def parse_sitemap(self: "ServiceSitemapMixinProtocol", sitemap_url: str) -> List[str]:
        return await self._sitemap_parser().parse_sitemap(sitemap_url)

    async def discover_urls(self: "ServiceSitemapMixinProtocol", html_content: str, base_url: str) -> List[str]:
        return await self._sitemap_service().discover_urls(html_content, base_url)

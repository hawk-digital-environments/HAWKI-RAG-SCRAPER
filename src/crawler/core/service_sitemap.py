import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, List, TYPE_CHECKING
import json

import aiohttp
from bs4 import BeautifulSoup

from hawki_crawler.crawler.core.sitemap_scraper import SitemapScraper
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
        """Check if URL is a sitemap"""
        url_lower = url.lower()
        if 'sitemap' in url_lower or url_lower.endswith('.xml'):
            return True
        if url_lower.endswith('.json'):
            return True
        return False

    async def parse_sitemap(self: "ServiceSitemapMixinProtocol", sitemap_url: str) -> List[str]:
        """Parse sitemap and extract URLs"""
        urls_with_dates = []
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(
                    sitemap_url,
                    timeout=aiohttp.ClientTimeout(total=30),
                    allow_redirects=True
                ) as response:
                    if response.status != 200:
                        LOGGER.warning(
                            "Error fetching sitemap %s: HTTP %s",
                            sitemap_url,
                            response.status,
                            extra={"job_id": getattr(self, "job_id", None)},
                        )
                        return []

                    content_type = response.headers.get("content-type", "")
                    content = await response.read()
                    content_stripped = content[:1].decode("utf-8", errors="ignore")

                    if "json" in content_type or sitemap_url.lower().endswith(".json") or content_stripped.startswith("{"):
                        try:
                            data = json.loads(content.decode("utf-8"))
                            urls = []
                            for url, meta in data.items():
                                if self.is_forbidden_url(url):
                                    continue
                                normalized_meta = self._normalize_sitemap_meta(meta)
                                lastmod_date = self.get_sitemap_date(normalized_meta)
                                if lastmod_date:
                                    self.sitemap_lastmod[url] = lastmod_date
                                urls_with_dates.append((url, lastmod_date))
                                urls.append(url)
                                key = self._normalize_url_key(url)
                                if key:
                                    self.sitemap_map[key] = normalized_meta
                            LOGGER.info(
                                "Detected JSON sitemap with %s URLs",
                                len(urls),
                                extra={"job_id": getattr(self, "job_id", None)},
                            )
                        except Exception as e:
                            LOGGER.error(
                                "Error parsing JSON sitemap: %s",
                                e,
                                extra={"job_id": getattr(self, "job_id", None)},
                            )
                        if self.url_tracking_manager:
                            await self.url_tracking_manager.add_urls_from_sitemap(urls_with_dates)
                        return [u for u, _ in urls_with_dates]

                    soup = BeautifulSoup(content, "xml")

                    sitemap_tags = soup.find_all('sitemap')
                    if sitemap_tags:
                        urls = []
                        for sitemap in sitemap_tags:
                            loc = sitemap.find('loc')
                            if loc and loc.text:
                                nested_urls = await self.parse_sitemap(loc.text)
                                urls.extend(nested_urls)
                        return urls

                    url_tags = soup.find_all('url')
                    urls = []
                    if url_tags:
                        for url_tag in url_tags:
                            loc = url_tag.find('loc')
                            if not loc or not loc.text:
                                continue
                            url = loc.text.strip()
                            if self.is_forbidden_url(url):
                                continue
                            lastmod_tag = url_tag.find('lastmod')
                            lastmod_date = None
                            if lastmod_tag and lastmod_tag.text:
                                lastmod_date = lastmod_tag.text.strip()
                                self.sitemap_lastmod[url] = lastmod_date
                            urls_with_dates.append((url, lastmod_date))
                            urls.append(url)
                        if self.url_tracking_manager:
                            await self.url_tracking_manager.add_urls_from_sitemap(urls_with_dates)
                        return urls

                    content_text = content.decode("utf-8", errors="ignore")
                    lines = [
                        line.strip()
                        for line in content_text.splitlines()
                        if line.strip() and not self.is_forbidden_url(line.strip())
                    ]
                    return lines

        except Exception as e:
            LOGGER.error(
                "Error parsing sitemap %s: %s",
                sitemap_url,
                e,
                extra={"job_id": getattr(self, "job_id", None)},
            )

        return []

    async def discover_urls(self: "ServiceSitemapMixinProtocol", html_content: str, base_url: str) -> List[str]:
        return await self._sitemap_service().discover_urls(html_content, base_url)

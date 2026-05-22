import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from urllib.parse import urljoin
from email.utils import parsedate_to_datetime

import aiohttp
from bs4 import BeautifulSoup

from hawki_crawler.crawler.core.sitemap_scraper import SitemapScraper

if TYPE_CHECKING:
    from hawki_crawler.crawler.core.protocols import CrawlerServiceProtocol

LOGGER = logging.getLogger("crawler.sitemap")


class ServiceSitemapMixin:
    def _normalize_url_key(self, url: str) -> Optional[str]:
        """Create a normalized key for quick sitemap map lookup."""
        if not url:
            return None
        url = url.strip()
        if not url:
            return None
        if url.startswith("http://"):
            url = url[len("http://"):]
        elif url.startswith("https://"):
            url = url[len("https://"):]
        if url.startswith("www."):
            url = url[len("www."):]
        return url.rstrip("/")

    def _normalize_sitemap_meta(self, meta: Any) -> Dict[str, Any]:
        """Normalize sitemap metadata into a dict with a last_modified key when possible."""
        if isinstance(meta, dict):
            normalized = dict(meta)
        else:
            normalized = {"last_modified": meta}
        if not normalized.get("last_modified"):
            normalized["last_modified"] = (
                normalized.get("lastmod")
                or normalized.get("date")
                or normalized.get("published_at")
            )
        return normalized

    def get_sitemap_date(self, entry: Optional[Dict[str, Any]]) -> Optional[str]:
        """Return the sitemap date from a sitemap entry when available."""
        if not entry:
            return None
        if not isinstance(entry, dict):
            return str(entry)
        return (
            entry.get("last_modified")
            or entry.get("lastmod")
            or entry.get("date")
            or entry.get("published_at")
        )

    def load_sitemap_map(self: "CrawlerServiceProtocol", path: str) -> Dict[str, Dict[str, str]]:
        """Load sitemap JSON into a normalized dict; silent fallback to empty."""
        if not path:
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                return {}
            normalized = {}
            for url, meta in raw.items():
                key = self._normalize_url_key(url)
                if not key:
                    continue
                normalized[key] = self._normalize_sitemap_meta(meta)
            return normalized
        except Exception:
            return {}

    def load_sitemap_urls(self: "CrawlerServiceProtocol", path: str) -> List[str]:
        """Load sitemap JSON and preserve full URLs for crawl seeding."""
        if not path:
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                return []
            urls: List[str] = []
            for url in raw.keys():
                if not isinstance(url, str):
                    continue
                if self.is_forbidden_url(url):
                    continue
                urls.append(url)
            return urls
        except Exception:
            return []

    def lookup_sitemap_entry(self: "CrawlerServiceProtocol", url: str) -> Optional[Dict[str, str]]:
        key = self._normalize_url_key(url)
        if not key:
            return None
        return self.sitemap_map.get(key)

    def first_sitemap_entry(self: "CrawlerServiceProtocol", *urls: str) -> Optional[Dict[str, str]]:
        """Return the first sitemap entry found for the provided URLs."""
        for u in urls:
            entry = self.lookup_sitemap_entry(u)
            if entry:
                return entry
        return None

    def parse_http_date(self, date_str: Optional[str]) -> Optional[str]:
        if not date_str:
            return None
        try:
            dt = parsedate_to_datetime(date_str)
            if dt:
                return dt.isoformat()
        except Exception:
            return None
        return None

    async def run_sitemap_scrape(self: "CrawlerServiceProtocol"):
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

    async def parse_sitemap(self: "CrawlerServiceProtocol", sitemap_url: str) -> List[str]:
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

    async def discover_urls(self: "CrawlerServiceProtocol", html_content: str, base_url: str) -> List[str]:
        """Extract links from HTML and normalize them."""
        soup = BeautifulSoup(html_content, 'html.parser')
        links = []
        for a in soup.find_all('a'):
            href = a.get('href')
            if not href:
                continue
            if str(href).startswith("#"):
                continue
            absolute = urljoin(base_url, href)
            absolute = self.normalize_url(absolute)
            if not self.is_discovery_url_allowed(absolute):
                continue
            if absolute not in links:
                links.append(absolute)
        return links

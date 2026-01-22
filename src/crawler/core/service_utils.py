import json
import os
import re
from pathlib import Path
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin
from email.utils import parsedate_to_datetime

import aiohttp
from bs4 import BeautifulSoup

from src.crawler.core.sitemap_scraper import SitemapScraper, DEFAULT_SITEMAP_BASE


class ServiceUtilsMixin:
    def _is_video_url(self, url: str) -> bool:
        return url.lower().split('?')[0].endswith((
            ".mp4", ".webm", ".mov", ".avi", ".mkv", ".flv", ".wmv",
            ".m4v", ".3gp", ".3g2", ".ts"
        ))

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

    def _load_sitemap_map(self, path: str) -> Dict[str, Dict[str, str]]:
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
                if isinstance(meta, dict):
                    normalized[key] = meta
                else:
                    normalized[key] = {"last_modified": meta}
            return normalized
        except Exception:
            return {}

    def _lookup_sitemap_entry(self, url: str) -> Optional[Dict[str, str]]:
        key = self._normalize_url_key(url)
        if not key:
            return None
        return self.sitemap_map.get(key)

    def _first_sitemap_entry(self, *urls: str) -> Optional[Dict[str, str]]:
        """Return the first sitemap entry found for the provided URLs."""
        for u in urls:
            entry = self._lookup_sitemap_entry(u)
            if entry:
                return entry
        return None

    def _parse_http_date(self, date_str: Optional[str]) -> Optional[str]:
        if not date_str:
            return None
        try:
            dt = parsedate_to_datetime(date_str)
            if dt:
                return dt.isoformat()
        except Exception:
            return None
        return None

    async def _run_sitemap_scrape(self):
        """Optionally scrape the sitemap JSON before crawling."""
        if not getattr(self.config, "sitemap", False):
            return
        base_url = self.sitemap_base or DEFAULT_SITEMAP_BASE
        output_path = Path(self.sitemap_path)
        start_page = self.config.sitemap_start_page or int(os.getenv("SITEMAP_START", "1"))
        max_pages = self.config.sitemap_pages or int(os.getenv("SITEMAP_PAGES", "6"))

        try:
            scraper = SitemapScraper(
                base_url=base_url,
                output_path=str(output_path),
                start_page=start_page,
                max_pages=max_pages
            )
            await scraper.run()
            self.sitemap_map = self._load_sitemap_map(str(output_path))
        except Exception as e:
            print(f"Error scraping HAWK sitemap: {e}")

    async def is_sitemap(self, url: str) -> bool:
        """Check if URL is a sitemap"""
        url_lower = url.lower()
        if 'sitemap' in url_lower or url_lower.endswith('.xml'):
            return True
        if url_lower.endswith('.json'):
            return True
        return False

    async def parse_sitemap(self, sitemap_url: str) -> List[str]:
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
                        print(f"Error fetching sitemap {sitemap_url}: HTTP {response.status}")
                        return []

                    content_type = response.headers.get("content-type", "")
                    content = await response.read()
                    content_stripped = content[:1].decode("utf-8", errors="ignore")

                    # Handle JSON sitemap (URL -> metadata)
                    if "json" in content_type or sitemap_url.lower().endswith(".json") or content_stripped.startswith("{"):
                        try:
                            data = json.loads(content.decode("utf-8"))
                            urls = list(data.keys())
                            for url in urls:
                                meta = data.get(url, {})
                                lastmod_date = None
                                if isinstance(meta, dict):
                                    lastmod_date = meta.get("last_modified") or meta.get("lastmod") or meta.get("date")
                                if lastmod_date:
                                    self.sitemap_lastmod[url] = lastmod_date
                                urls_with_dates.append((url, lastmod_date))
                            print(f"Detected JSON sitemap with {len(urls)} URLs")
                        except Exception as e:
                            print(f"Error parsing JSON sitemap: {e}")
                        if self.url_tracking_manager:
                            await self.url_tracking_manager.add_urls_from_sitemap(urls_with_dates)
                        return [u for u, _ in urls_with_dates]

                    soup = BeautifulSoup(content, "xml")

                    # Handle sitemap index
                    sitemap_tags = soup.find_all('sitemap')
                    if sitemap_tags:
                        urls = []
                        for sitemap in sitemap_tags:
                            loc = sitemap.find('loc')
                            if loc and loc.text:
                                nested_urls = await self.parse_sitemap(loc.text)
                                urls.extend(nested_urls)
                        return urls

                    # Handle URL set
                    url_tags = soup.find_all('url')
                    urls = []
                    if url_tags:
                        for url_tag in url_tags:
                            loc = url_tag.find('loc')
                            if not loc or not loc.text:
                                continue
                            url = loc.text.strip()
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

                    # Handle plain text fallback
                    content_text = content.decode("utf-8", errors="ignore")
                    lines = [line.strip() for line in content_text.splitlines() if line.strip()]
                    return lines

        except Exception as e:
            print(f"Error parsing sitemap {sitemap_url}: {e}")

        return []

    async def discover_urls(self, html_content: str, base_url: str) -> List[str]:
        """Extract links from HTML and normalize them."""
        soup = BeautifulSoup(html_content, 'html.parser')
        links = []
        for a in soup.find_all('a'):
            href = a.get('href')
            if not href:
                continue
            absolute = urljoin(base_url, href)
            if absolute not in links:
                links.append(absolute)
        return links


def assess_content_quality(markdown: str, min_word_count: int) -> Dict[str, Any]:
    """
    Simple content quality check based on word count.
    """
    word_count = len(re.findall(r"[A-Za-z0-9_]+", markdown))
    if min_word_count <= 0:
        return {
            "word_count": word_count,
            "is_low_quality": False,
            "reason": None
        }

    if word_count < min_word_count:
        return {
            "word_count": word_count,
            "is_low_quality": True,
            "reason": f"word_count_below_{min_word_count}"
        }

    return {
        "word_count": word_count,
        "is_low_quality": False,
        "reason": None
    }

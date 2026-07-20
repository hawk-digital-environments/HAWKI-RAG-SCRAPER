import json
import logging
from typing import Any, Callable, Dict, List, Optional

import aiohttp
from bs4 import BeautifulSoup


LOGGER = logging.getLogger("crawler.sitemap")


class SitemapParser:
    """Fetch and parse JSON, XML, and text sitemap resources."""

    def __init__(
        self,
        *,
        headers: Dict[str, str],
        sitemap_map: Dict[str, Dict[str, Any]],
        sitemap_lastmod: Dict[str, str],
        is_forbidden_url: Callable[[str], bool],
        normalize_url_key: Callable[[str], Optional[str]],
        normalize_sitemap_meta: Callable[[Any], Dict[str, Any]],
        get_sitemap_date: Callable[[Optional[Dict[str, Any]]], Optional[str]],
        url_tracking_manager: Any = None,
        job_id: Optional[str] = None,
    ) -> None:
        self.headers = headers
        self.sitemap_map = sitemap_map
        self.sitemap_lastmod = sitemap_lastmod
        self.is_forbidden_url = is_forbidden_url
        self.normalize_url_key = normalize_url_key
        self.normalize_sitemap_meta = normalize_sitemap_meta
        self.get_sitemap_date = get_sitemap_date
        self.url_tracking_manager = url_tracking_manager
        self.job_id = job_id

    @staticmethod
    def is_sitemap(url: str) -> bool:
        """Return True when a URL looks like a sitemap resource."""
        url_lower = url.lower()
        if "sitemap" in url_lower or url_lower.endswith(".xml"):
            return True
        if url_lower.endswith(".json"):
            return True
        return False

    async def parse_sitemap(self, sitemap_url: str) -> List[str]:
        """Parse sitemap resources and return crawlable URLs."""
        urls_with_dates = []
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(
                    sitemap_url,
                    timeout=aiohttp.ClientTimeout(total=30),
                    allow_redirects=True,
                ) as response:
                    if response.status != 200:
                        LOGGER.warning(
                            "Error fetching sitemap %s: HTTP %s",
                            sitemap_url,
                            response.status,
                            extra={"job_id": self.job_id},
                        )
                        return []

                    content_type = response.headers.get("content-type", "")
                    content = await response.read()
                    content_stripped = content[:1].decode("utf-8", errors="ignore")

                    is_json_sitemap = (
                        "json" in content_type
                        or sitemap_url.lower().endswith(".json")
                        or content_stripped.startswith("{")
                    )
                    if is_json_sitemap:
                        return await self._parse_json_sitemap(content, urls_with_dates)

                    soup = BeautifulSoup(content, "xml")

                    sitemap_tags = soup.find_all("sitemap")
                    if sitemap_tags:
                        urls = []
                        for sitemap in sitemap_tags:
                            loc = sitemap.find("loc")
                            if loc and loc.text:
                                nested_urls = await self.parse_sitemap(loc.text)
                                urls.extend(nested_urls)
                        return urls

                    url_tags = soup.find_all("url")
                    if url_tags:
                        return await self._parse_xml_urlset(url_tags, urls_with_dates)

                    return self._parse_text_sitemap(content)

        except Exception as exc:
            LOGGER.error(
                "Error parsing sitemap %s: %s",
                sitemap_url,
                exc,
                extra={"job_id": self.job_id},
            )

        return []

    async def _parse_json_sitemap(
        self,
        content: bytes,
        urls_with_dates: List[tuple[str, Optional[str]]],
    ) -> List[str]:
        try:
            data = json.loads(content.decode("utf-8"))
            urls = []
            for url, meta in data.items():
                if self.is_forbidden_url(url):
                    continue
                normalized_meta = self.normalize_sitemap_meta(meta)
                lastmod_date = self.get_sitemap_date(normalized_meta)
                if lastmod_date:
                    self.sitemap_lastmod[url] = lastmod_date
                urls_with_dates.append((url, lastmod_date))
                urls.append(url)
                key = self.normalize_url_key(url)
                if key:
                    self.sitemap_map[key] = normalized_meta
            LOGGER.info(
                "Detected JSON sitemap with %s URLs",
                len(urls),
                extra={"job_id": self.job_id},
            )
        except Exception as exc:
            LOGGER.error(
                "Error parsing JSON sitemap: %s",
                exc,
                extra={"job_id": self.job_id},
            )
        if self.url_tracking_manager:
            await self.url_tracking_manager.add_urls_from_sitemap(urls_with_dates)
        return [url for url, _ in urls_with_dates]

    async def _parse_xml_urlset(
        self,
        url_tags: Any,
        urls_with_dates: List[tuple[str, Optional[str]]],
    ) -> List[str]:
        urls = []
        for url_tag in url_tags:
            loc = url_tag.find("loc")
            if not loc or not loc.text:
                continue
            url = loc.text.strip()
            if self.is_forbidden_url(url):
                continue
            lastmod_tag = url_tag.find("lastmod")
            lastmod_date = None
            if lastmod_tag and lastmod_tag.text:
                lastmod_date = lastmod_tag.text.strip()
                self.sitemap_lastmod[url] = lastmod_date
            urls_with_dates.append((url, lastmod_date))
            urls.append(url)
        if self.url_tracking_manager:
            await self.url_tracking_manager.add_urls_from_sitemap(urls_with_dates)
        return urls

    def _parse_text_sitemap(self, content: bytes) -> List[str]:
        content_text = content.decode("utf-8", errors="ignore")
        return [
            line.strip()
            for line in content_text.splitlines()
            if line.strip() and not self.is_forbidden_url(line.strip())
        ]

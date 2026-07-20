import json
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup


class SitemapService:
    """Pure sitemap helpers and HTML link discovery."""

    def __init__(
        self,
        *,
        sitemap_map: Optional[Dict[str, Dict[str, Any]]] = None,
        is_forbidden_url: Optional[Callable[[str], bool]] = None,
        is_discovery_url_allowed: Optional[Callable[[str], bool]] = None,
        normalize_url: Optional[Callable[[str], str]] = None,
    ) -> None:
        self.sitemap_map = sitemap_map if sitemap_map is not None else {}
        self.is_forbidden_url = is_forbidden_url or (lambda url: False)
        self.is_discovery_url_allowed = is_discovery_url_allowed or (lambda url: True)
        self.normalize_url = normalize_url or (lambda url: url)

    @staticmethod
    def normalize_url_key(url: str) -> Optional[str]:
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

    @staticmethod
    def normalize_sitemap_meta(meta: Any) -> Dict[str, Any]:
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

    @staticmethod
    def get_sitemap_date(entry: Optional[Dict[str, Any]]) -> Optional[str]:
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

    def load_sitemap_map(self, path: str) -> Dict[str, Dict[str, Any]]:
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
                key = self.normalize_url_key(url)
                if not key:
                    continue
                normalized[key] = self.normalize_sitemap_meta(meta)
            return normalized
        except Exception:
            return {}

    def load_sitemap_urls(self, path: str) -> List[str]:
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

    def lookup_sitemap_entry(self, url: str) -> Optional[Dict[str, Any]]:
        key = self.normalize_url_key(url)
        if not key:
            return None
        return self.sitemap_map.get(key)

    def first_sitemap_entry(self, *urls: str) -> Optional[Dict[str, Any]]:
        """Return the first sitemap entry found for the provided URLs."""
        for url in urls:
            entry = self.lookup_sitemap_entry(url)
            if entry:
                return entry
        return None

    @staticmethod
    def parse_http_date(date_str: Optional[str]) -> Optional[str]:
        if not date_str:
            return None
        try:
            dt = parsedate_to_datetime(date_str)
            if dt:
                return dt.isoformat()
        except Exception:
            return None
        return None

    async def discover_urls(self, html_content: str, base_url: str) -> List[str]:
        """Extract links from HTML and normalize them."""
        soup = BeautifulSoup(html_content, "html.parser")
        links = []
        for anchor in soup.find_all("a"):
            href = anchor.get("href")
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

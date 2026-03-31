import json
import os
import re
from pathlib import Path
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin, urlparse, parse_qs
from email.utils import parsedate_to_datetime

import aiohttp
from bs4 import BeautifulSoup

from src.crawler.core.sitemap_scraper import SitemapScraper


class ServiceUtilsMixin:
    def _get_forbidden_file_candidates(self) -> List[Path]:
        profile_file = (getattr(self, "site_profile", {}) or {}).get("forbidden", {}).get("rules_file")
        candidates = []
        if profile_file:
            candidates.append(Path(profile_file))
        candidates.extend([
            Path(os.getenv("FORBIDDEN_URLS_FILE", "")),
            Path("/app/forbidden_urls.txt"),
            Path("/app/shared/forbidden_urls.txt"),
            Path("forbidden_urls.txt"),
        ])
        return candidates

    def _get_forbidden_hosts(self) -> set:
        """Load forbidden hosts from forbidden_urls.txt."""
        candidates = self._get_forbidden_file_candidates()
        hosts = set((getattr(self, "site_profile", {}) or {}).get("forbidden", {}).get("hosts", []))
        for path in candidates:
            if not path or str(path) == ".":
                continue
            if not path.exists():
                continue
            try:
                with path.open("r", encoding="utf-8") as f:
                    for line in f:
                        entry = line.strip()
                        if not entry or entry.startswith("#"):
                            continue
                        if "/" in entry or "?" in entry:
                            continue
                        hosts.add(entry.lower())
            except Exception:
                continue
        return hosts

    def _get_forbidden_url_patterns(self) -> List[str]:
        """Load forbidden URL patterns from forbidden_urls.txt."""
        candidates = self._get_forbidden_file_candidates()
        patterns: List[str] = list((getattr(self, "site_profile", {}) or {}).get("forbidden", {}).get("url_patterns", []))
        for path in candidates:
            if not path or str(path) == ".":
                continue
            if not path.exists():
                continue
            try:
                with path.open("r", encoding="utf-8") as f:
                    for line in f:
                        entry = line.strip()
                        if not entry or entry.startswith("#"):
                            continue
                        if "/" in entry or "?" in entry:
                            patterns.append(entry.lower())
            except Exception:
                continue
        return patterns

    def _is_forbidden_host(self, host: str) -> bool:
        """Return True when a host should never be crawled."""
        if not host:
            return True
        host = host.lower()
        forbidden_hosts = self._get_forbidden_hosts()
        if host in forbidden_hosts:
            return True
        for forbidden in forbidden_hosts:
            if host.endswith(f".{forbidden}"):
                return True
        return False

    def _is_forbidden_url(self, url: str) -> bool:
        """Return True when a specific URL should never be crawled."""
        if not url:
            return True
        url_lower = url.lower()
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if self._is_forbidden_host(host):
            return True
        for pattern in self._get_forbidden_url_patterns():
            if pattern in url_lower:
                return True
        path = (parsed.path or "").rstrip("/")
        if path == "/de/form/contact":
            query = parse_qs(parsed.query or "")
            form_type = query.get("form_type", [""])[0]
            if form_type in ("person", "functioncontact") and "entity_key" in query:
                return True
        return False

    def _allowed_discovery_hosts(self) -> List[str]:
        profile_hosts = (getattr(self, "site_profile", {}) or {}).get("discovery", {}).get("allowed_hosts") or []
        if profile_hosts:
            return [str(host).lower() for host in profile_hosts]
        crawl_host = (self.crawl_host or "").lower()
        return [crawl_host] if crawl_host else []

    def _is_discovery_url_allowed(self, url: str) -> bool:
        """Allow only configured discovery hosts for crawl expansion."""
        if not url:
            return False
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").lower()
        if not host:
            return False
        if self._is_forbidden_url(url):
            return False
        for allowed in self._allowed_discovery_hosts():
            if host == allowed or host.endswith(f".{allowed}"):
                return True
        return False

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

    def _get_sitemap_date(self, entry: Optional[Dict[str, Any]]) -> Optional[str]:
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
                normalized[key] = self._normalize_sitemap_meta(meta)
            return normalized
        except Exception:
            return {}

    def _load_sitemap_urls(self, path: str) -> List[str]:
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
                if self._is_forbidden_url(url):
                    continue
                urls.append(url)
            return urls
        except Exception:
            return []

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
            self.sitemap_map = self._load_sitemap_map(str(output_path))
            self.sitemap_urls = self._load_sitemap_urls(str(output_path))
        except Exception as e:
            print(f"Error scraping sitemap: {e}")

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
                            urls = []
                            for url, meta in data.items():
                                if self._is_forbidden_url(url):
                                    continue
                                normalized_meta = self._normalize_sitemap_meta(meta)
                                lastmod_date = self._get_sitemap_date(normalized_meta)
                                if lastmod_date:
                                    self.sitemap_lastmod[url] = lastmod_date
                                urls_with_dates.append((url, lastmod_date))
                                urls.append(url)
                                key = self._normalize_url_key(url)
                                if key:
                                    self.sitemap_map[key] = normalized_meta
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
                            if self._is_forbidden_url(url):
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

                    # Handle plain text fallback
                    content_text = content.decode("utf-8", errors="ignore")
                    lines = [
                        line.strip()
                        for line in content_text.splitlines()
                        if line.strip() and not self._is_forbidden_url(line.strip())
                    ]
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
            if str(href).startswith("#"):
                continue
            absolute = urljoin(base_url, href)
            absolute = self.normalize_url(absolute)
            if not self._is_discovery_url_allowed(absolute):
                continue
            if absolute not in links:
                links.append(absolute)
        return links

def detect_language_confidence(lang: Optional[str], markdown: str) -> float:
    if not markdown or not markdown.strip():
        return 0.0
    if not lang:
        return 0.25
    word_count = len(re.findall(r"\b\w+\b", markdown))
    if word_count >= 150:
        return 0.95
    if word_count >= 75:
        return 0.85
    if word_count >= 25:
        return 0.7
    return 0.55


def assess_content_quality(
    markdown: str,
    min_word_count: int,
    *,
    link_density: float = 0.0,
    heading_count: int = 0,
    paragraph_count: int = 0,
    duplicate_ratio: float = 0.0,
    boilerplate_ratio: float = 0.0,
    language_confidence: float = 0.0,
) -> Dict[str, Any]:
    """
    Richer content quality assessment with structural and noise signals.
    """
    word_count = len(re.findall(r"[A-Za-z0-9_]+", markdown))
    score = 0.0
    score += min(word_count / 4.0, 45.0)
    score += min(heading_count * 3.0, 15.0)
    score += min(paragraph_count * 1.5, 15.0)
    score += max(0.0, (1.0 - min(link_density, 1.0))) * 12.0
    score += max(0.0, (1.0 - min(duplicate_ratio, 1.0))) * 8.0
    score += max(0.0, (1.0 - min(boilerplate_ratio, 1.0))) * 10.0
    score += max(0.0, min(language_confidence, 1.0)) * 10.0
    score = max(0.0, min(100.0, score))

    reasons: List[str] = []
    if min_word_count > 0 and word_count < min_word_count:
        reasons.append(f"word_count_below_{min_word_count}")
    if link_density > 0.6:
        reasons.append("high_link_density")
    if duplicate_ratio > 0.35:
        reasons.append("high_duplicate_ratio")
    if boilerplate_ratio > 0.3:
        reasons.append("high_boilerplate_ratio")
    if paragraph_count == 0 and word_count > 40:
        reasons.append("missing_paragraph_structure")

    quality_label = "high"
    if score < 80:
        quality_label = "medium"
    if score < 55:
        quality_label = "low"
    if score < 30:
        quality_label = "very_low"

    content_classification = "success"
    if word_count == 0:
        content_classification = "empty"
    elif score < 30:
        content_classification = "partial"
    elif score < 45:
        content_classification = "noisy"

    return {
        "score": round(score, 2),
        "quality_label": quality_label,
        "content_classification": content_classification,
        "is_low_quality": bool(reasons) or score < 45,
        "reason": reasons[0] if reasons else None,
        "reasons": reasons,
        "signals": {
            "word_count": word_count,
            "link_density": round(link_density, 4),
            "heading_count": heading_count,
            "paragraph_count": paragraph_count,
            "duplicate_ratio": round(duplicate_ratio, 4),
            "boilerplate_ratio": round(boilerplate_ratio, 4),
            "language_confidence": round(language_confidence, 4),
        }
    }

import os
from pathlib import Path
from typing import List, TYPE_CHECKING
from urllib.parse import urlparse, parse_qs

if TYPE_CHECKING:
    from src.crawler.core.protocols import CrawlerServiceProtocol


class ServiceUrlPolicyMixin:
    def _get_forbidden_file_candidates(self: "CrawlerServiceProtocol") -> List[Path]:
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

    def get_forbidden_hosts(self: "CrawlerServiceProtocol") -> set:
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

    def _get_forbidden_url_patterns(self: "CrawlerServiceProtocol") -> List[str]:
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

    def _is_forbidden_host(self: "CrawlerServiceProtocol", host: str) -> bool:
        """Return True when a host should never be crawled."""
        if not host:
            return True
        host = host.lower()
        forbidden_hosts = self.get_forbidden_hosts()
        if host in forbidden_hosts:
            return True
        for forbidden in forbidden_hosts:
            if host.endswith(f".{forbidden}"):
                return True
        return False

    def is_forbidden_url(self: "CrawlerServiceProtocol", url: str) -> bool:
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

    def _allowed_discovery_hosts(self: "CrawlerServiceProtocol") -> List[str]:
        profile_hosts = (getattr(self, "site_profile", {}) or {}).get("discovery", {}).get("allowed_hosts") or []
        if profile_hosts:
            return [str(host).lower() for host in profile_hosts]
        crawl_host = (self.crawl_host or "").lower()
        return [crawl_host] if crawl_host else []

    def is_discovery_url_allowed(self: "CrawlerServiceProtocol", url: str) -> bool:
        """Allow only configured discovery hosts for crawl expansion."""
        if not url:
            return False
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").lower()
        if not host:
            return False
        if self.is_forbidden_url(url):
            return False
        for allowed in self._allowed_discovery_hosts():
            if host == allowed or host.endswith(f".{allowed}"):
                return True
        return False

    def is_video_url(self, url: str) -> bool:
        return url.lower().split('?')[0].endswith((
            ".mp4", ".webm", ".mov", ".avi", ".mkv", ".flv", ".wmv",
            ".m4v", ".3gp", ".3g2", ".ts"
        ))

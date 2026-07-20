import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import parse_qs, urlparse

from hawki_crawler.crawler.policies.url_normalization import normalize_url


FILE_EXTENSIONS = (
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods",
    ".odp", ".rtf", ".txt", ".csv", ".zip", ".rar", ".7z",
)
DISALLOWED_FILE_EXTENSIONS = (".exe",)
VIDEO_EXTENSIONS = (
    ".mp4", ".webm", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".m4v",
    ".3gp", ".3g2", ".ts",
)


class ResourcePolicy:
    """Rules that classify resources and decide which URLs may be crawled."""

    def __init__(
        self,
        *,
        site_profile: Optional[Dict[str, Any]] = None,
        crawl_host: Optional[str] = None,
    ) -> None:
        self.site_profile = site_profile or {}
        self.crawl_host = crawl_host

    @property
    def forbidden_profile(self) -> Dict[str, Any]:
        return (self.site_profile or {}).get("forbidden", {}) or {}

    @property
    def discovery_profile(self) -> Dict[str, Any]:
        return (self.site_profile or {}).get("discovery", {}) or {}

    def get_forbidden_files(self) -> List[Path]:
        """Return configured forbidden-rule paths that point to existing files."""
        candidates: List[Path] = []

        if profile_file := self.forbidden_profile.get("rules_file"):
            candidates.append(Path(profile_file))

        if environment_file := os.getenv("FORBIDDEN_URLS_FILE"):
            candidates.append(Path(environment_file))

        candidates.extend(
            [
                Path("/var/www/html/forbidden_urls.txt"),
                Path("/var/www/html/shared/forbidden_urls.txt"),
                Path("forbidden_urls.txt"),
            ]
        )
        return [path for path in candidates if path.is_file()]

    def get_forbidden_hosts(self) -> Set[str]:
        """Load forbidden hosts from the site profile and forbidden URL files."""
        hosts = {str(host).lower() for host in self.forbidden_profile.get("hosts", [])}
        for path in self.get_forbidden_files():
            try:
                with path.open("r", encoding="utf-8") as file:
                    for line in file:
                        entry = line.strip()
                        if not entry or entry.startswith("#"):
                            continue
                        if "/" in entry or "?" in entry:
                            continue
                        hosts.add(entry.lower())
            except Exception:
                continue
        return hosts

    def get_forbidden_url_patterns(self) -> List[str]:
        """Load forbidden URL patterns from the site profile and rules files."""
        patterns = [
            str(pattern).lower()
            for pattern in self.forbidden_profile.get("url_patterns", [])
        ]
        for path in self.get_forbidden_files():
            try:
                with path.open("r", encoding="utf-8") as file:
                    for line in file:
                        entry = line.strip()
                        if not entry or entry.startswith("#"):
                            continue
                        if "/" in entry or "?" in entry:
                            patterns.append(entry.lower())
            except Exception:
                continue
        return patterns

    def is_forbidden_host(self, host: str) -> bool:
        """Return True when a host should never be crawled."""
        if not host:
            return True
        host = host.lower()
        forbidden_hosts = self.get_forbidden_hosts()
        if host in forbidden_hosts:
            return True
        return any(host.endswith(f".{forbidden}") for forbidden in forbidden_hosts)

    def is_forbidden_url(self, url: str) -> bool:
        """Return True when a specific URL should never be crawled."""
        if not url:
            return True
        url_lower = url.lower()
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if self.is_forbidden_host(host):
            return True
        if any(pattern in url_lower for pattern in self.get_forbidden_url_patterns()):
            return True
        path = (parsed.path or "").rstrip("/")
        if path == "/de/form/contact":
            query = parse_qs(parsed.query or "")
            form_type = query.get("form_type", [""])[0]
            if form_type in ("person", "functioncontact") and "entity_key" in query:
                return True
        return False

    def allowed_discovery_hosts(self) -> List[str]:
        profile_hosts = self.discovery_profile.get("allowed_hosts") or []
        if profile_hosts:
            return [str(host).lower() for host in profile_hosts]
        crawl_host = (self.crawl_host or "").lower()
        return [crawl_host] if crawl_host else []

    def is_discovery_url_allowed(self, url: str) -> bool:
        """Allow only configured discovery hosts for crawl expansion."""
        if not url:
            return False
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").lower()
        if not host or self.is_forbidden_url(url):
            return False
        return any(
            host == allowed or host.endswith(f".{allowed}")
            for allowed in self.allowed_discovery_hosts()
        )

    @staticmethod
    def normalize_url(url: str) -> str:
        return normalize_url(url)

    @staticmethod
    def is_pdf_url(url: str) -> bool:
        return urlparse(url).path.lower().endswith(".pdf")

    @staticmethod
    def is_file_url(url: str) -> bool:
        path = urlparse(url).path.lower()
        if path.endswith(DISALLOWED_FILE_EXTENSIONS) or path.endswith(".pdf"):
            return False
        return path.endswith(FILE_EXTENSIONS)

    @staticmethod
    def is_video_url(url: str) -> bool:
        return urlparse(url).path.lower().endswith(VIDEO_EXTENSIONS)

    @staticmethod
    def looks_like_file_url(url: str) -> bool:
        path = urlparse(url).path.lower()
        return (
            path.endswith(DISALLOWED_FILE_EXTENSIONS)
            or path.endswith(".pdf")
            or path.endswith(FILE_EXTENSIONS)
            or ("/media/" in path and not path.endswith(".pdf"))
        )

    @staticmethod
    def is_pdf_resource(url: str, headers: Optional[Dict[str, str]] = None) -> bool:
        if ResourcePolicy.is_pdf_url(url):
            return True
        content_type = (headers or {}).get("content-type", "")
        return "pdf" in content_type.lower()

    @staticmethod
    def is_file_resource(url: str, headers: Optional[Dict[str, str]] = None) -> bool:
        path = urlparse(url).path.lower()
        if path.endswith(DISALLOWED_FILE_EXTENSIONS):
            return False
        if "/media/" in path and not path.endswith(".pdf"):
            return True
        if path.endswith(FILE_EXTENSIONS):
            return True
        if headers is None:
            return False

        content_type = headers.get("content-type", "").lower()
        if not content_type or content_type == "application/x-msdownload":
            return False
        if "text/html" in content_type or content_type.startswith("image/"):
            return False
        if content_type in ("text/css", "text/javascript", "application/javascript"):
            return False
        if "application/" in content_type or "octet-stream" in content_type:
            return True

        content_disposition = headers.get("content-disposition", "").lower()
        return "attachment" in content_disposition

    @staticmethod
    def should_skip_file_download(
        url: str,
        filename: Optional[str],
        content_type: str,
    ) -> bool:
        path = urlparse(url).path.lower()
        if path.endswith(DISALLOWED_FILE_EXTENSIONS):
            return True
        if filename and filename.lower().endswith(DISALLOWED_FILE_EXTENSIONS):
            return True
        if content_type == "application/x-msdownload" or not filename:
            return True
        return Path(filename).suffix == ""


class ResourcePolicyClientMixin:
    """Provide one shared policy attribute to crawler service mixins."""

    _resource_policy: ResourcePolicy

    @property
    def resource_policy(self) -> ResourcePolicy:
        return self._resource_policy

    @resource_policy.setter
    def resource_policy(self, policy: ResourcePolicy) -> None:
        self._resource_policy = policy

    @property
    def url_policy(self) -> ResourcePolicy:
        """Compatibility alias for integrations using the former attribute name."""
        return self.resource_policy

    @url_policy.setter
    def url_policy(self, policy: ResourcePolicy) -> None:
        self.resource_policy = policy

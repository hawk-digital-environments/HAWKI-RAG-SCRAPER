"""HEAD requests and resource classification for crawler assets."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

import aiohttp

from hawki_crawler.crawler.assets.asset_policy import AssetPolicy


FetchHeadCallable = Callable[[str], Awaitable[Tuple[Optional[int], Dict[str, str]]]]


class ResourceDetector:
    """Detect whether URLs point to PDFs or supported downloadable files."""

    def __init__(
        self,
        *,
        rate_limiter: Any,
        http_session: Optional[aiohttp.ClientSession],
        logger: Optional[Any] = None,
        policy: Optional[AssetPolicy] = None,
        fetch_head: Optional[FetchHeadCallable] = None,
    ) -> None:
        self.rate_limiter = rate_limiter
        self.http_session = http_session
        self.logger = logger or logging.getLogger("crawler")
        self.policy = policy or AssetPolicy()
        self._fetch_head_override = fetch_head

    async def fetch_head(self, url: str) -> Tuple[Optional[int], Dict[str, str]]:
        """Fetch HEAD request for a URL."""
        await self.rate_limiter.acquire()

        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with self.http_session.head(url, allow_redirects=True, timeout=timeout) as response:
                headers = {k.lower(): v for k, v in response.headers.items()}
                return response.status, headers
        except Exception as exc:
            self.logger.warning("HEAD request failed for %s: %s", url, exc)
            return None, {}

    async def resolve_head_headers(self, url: str, head_headers: Optional[Dict[str, str]]) -> Dict[str, str]:
        """Return provided headers or fetch them through the configured HEAD path."""
        if head_headers:
            return head_headers
        if self._fetch_head_override:
            result = await self._fetch_head_override(url)
        else:
            result = await self.fetch_head(url)
        if isinstance(result, tuple):
            return result[1]
        return result if isinstance(result, dict) else {}

    async def is_pdf_resource(
        self,
        url: str,
        head_status: Optional[int] = None,
        head_headers: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Check if a URL points directly to a PDF."""
        _ = head_status
        if self.policy.is_pdf_url(url):
            return True

        headers = await self.resolve_head_headers(url, head_headers)
        return self.policy.is_pdf_resource(url, headers)

    async def is_file_resource(
        self,
        url: str,
        head_status: Optional[int] = None,
        head_headers: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Check if a URL points directly to a non-PDF file."""
        _ = head_status
        if self.policy.is_file_resource(url, None):
            return True

        headers = await self.resolve_head_headers(url, head_headers)
        if not isinstance(headers, dict):
            return False

        return self.policy.is_file_resource(url, headers)

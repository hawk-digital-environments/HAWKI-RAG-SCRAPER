"""URL normalization helpers used by crawler policies and discovery."""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse


def normalize_url(url: str) -> str:
    """Normalize a crawl URL by removing fragments and trailing slashes."""
    parsed = urlparse(url)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip("/") or "/",
            parsed.params,
            parsed.query,
            "",
        )
    )

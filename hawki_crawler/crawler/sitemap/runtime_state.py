"""Runtime sitemap state resolution for crawler jobs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from hawki_crawler.crawler.sitemap.scraper import DEFAULT_SITEMAP_BASE


@dataclass
class SitemapRuntimeState:
    """Sitemap-related state attached to a crawler service instance."""

    sitemap_lastmod: Dict[str, str]
    sitemap_path: Optional[str]
    sitemap_map: Dict[str, Dict[str, Any]]
    sitemap_urls: List[str]
    sitemap_base: Optional[str]
    crawl_host: Optional[str]


def build_sitemap_runtime_state(
    *,
    config: Any,
    job_id: Optional[str],
    storage_manager: Optional[Any],
    site_profile: Dict[str, Any],
    load_sitemap_map: Callable[[Optional[str]], Dict[str, Dict[str, Any]]],
    load_sitemap_urls: Callable[[Optional[str]], List[str]],
) -> SitemapRuntimeState:
    """Resolve sitemap paths, load cached sitemap data, and derive crawl host."""
    default_sitemap_path = None
    if job_id and storage_manager:
        default_sitemap_path = str(storage_manager.get_job_directory() / "sitemap.json")

    sitemap_path = (
        config.sitemap_output
        or os.getenv("SITE_SITEMAP_JSON")
        or os.getenv("SITEMAP_JSON")
        or default_sitemap_path
    )
    profile_sitemap = (site_profile or {}).get("sitemap", {})
    sitemap_base = (
        config.sitemap_base
        or os.getenv("SITEMAP_BASE")
        or profile_sitemap.get("base_url")
        or DEFAULT_SITEMAP_BASE
    )

    return SitemapRuntimeState(
        sitemap_lastmod={},
        sitemap_path=sitemap_path,
        sitemap_map=load_sitemap_map(sitemap_path),
        sitemap_urls=load_sitemap_urls(sitemap_path),
        sitemap_base=sitemap_base,
        crawl_host=urlparse(str(config.url)).hostname,
    )

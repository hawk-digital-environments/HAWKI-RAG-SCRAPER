"""Crawl4AI run configuration helpers."""

from __future__ import annotations

from crawl4ai.async_configs import CacheMode, CrawlerRunConfig

from hawki_crawler.crawler.models import CrawlConfig


def build_crawler_run_config(config: CrawlConfig) -> CrawlerRunConfig:
    """Build the shared Crawl4AI run config for single-page and batch crawls."""
    return CrawlerRunConfig(
        word_count_threshold=0,
        exclude_external_links=False,
        process_iframes=False,
        remove_overlay_elements=True,
        cache_mode=CacheMode.BYPASS,
        wait_until=config.wait_until,
        page_timeout=config.page_timeout_ms,
        delay_before_return_html=5.0,
    )

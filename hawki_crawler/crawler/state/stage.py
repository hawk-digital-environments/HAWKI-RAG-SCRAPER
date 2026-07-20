from enum import Enum


class Stage(Enum):
    """Internal crawler lifecycle stages used for local progress tracking."""

    INITIALIZATION = "initialization"
    SITEMAP_DETECTED = "sitemap_detected"
    URLS_DISCOVERED = "urls_discovered"
    CRAWLING_STARTED = "crawling_started"
    SCRAPING = "scraping"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"

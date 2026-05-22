"""Compatibility package for shared contracts."""

from hawki_crawler.common.job_schema import CrawlJob
from hawki_crawler.common.pipeline_events import FileDiscoveredEvent

__all__ = ["CrawlJob", "FileDiscoveredEvent"]

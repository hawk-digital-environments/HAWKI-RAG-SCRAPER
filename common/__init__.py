"""Compatibility package for shared contracts."""

from common.job_schema import CrawlJob
from common.pipeline_events import FileDiscoveredEvent

__all__ = ["CrawlJob", "FileDiscoveredEvent"]

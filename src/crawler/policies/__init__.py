"""Crawler policy services."""

from hawki_crawler.crawler.policies.url_normalization import normalize_url
from hawki_crawler.crawler.policies.url_policy import UrlPolicyService

__all__ = ["UrlPolicyService", "normalize_url"]

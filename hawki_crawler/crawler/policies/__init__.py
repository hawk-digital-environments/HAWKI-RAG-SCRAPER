"""Crawler policy services."""

from hawki_crawler.crawler.policies.url_normalization import normalize_url
from hawki_crawler.crawler.policies.url_policy import UrlPolicyService
from hawki_crawler.crawler.policies.resource_policy import ResourcePolicy

__all__ = ["ResourcePolicy", "UrlPolicyService", "normalize_url"]

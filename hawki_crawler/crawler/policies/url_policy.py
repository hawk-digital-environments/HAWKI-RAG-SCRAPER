"""Backward-compatible import for the former URL-only policy."""

from hawki_crawler.crawler.policies.resource_policy import ResourcePolicy

UrlPolicyService = ResourcePolicy

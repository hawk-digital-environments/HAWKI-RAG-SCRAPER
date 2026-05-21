from pathlib import Path
from typing import List, TYPE_CHECKING

from hawki_crawler.crawler.policies.url_policy import UrlPolicyService

if TYPE_CHECKING:
    from hawki_crawler.crawler.core.protocols import ServiceUrlPolicyMixinProtocol


class ServiceUrlPolicyMixin:
    """Compatibility mixin that delegates URL decisions to UrlPolicyService."""

    def _url_policy(self: "ServiceUrlPolicyMixinProtocol") -> UrlPolicyService:
        return UrlPolicyService(
            site_profile=getattr(self, "site_profile", {}) or {},
            crawl_host=getattr(self, "crawl_host", None),
        )

    def _get_forbidden_file_candidates(self: "ServiceUrlPolicyMixinProtocol") -> List[Path]:
        return self._url_policy().get_forbidden_file_candidates()

    def get_forbidden_hosts(self: "ServiceUrlPolicyMixinProtocol") -> set:
        return self._url_policy().get_forbidden_hosts()

    def _get_forbidden_url_patterns(self: "ServiceUrlPolicyMixinProtocol") -> List[str]:
        return self._url_policy().get_forbidden_url_patterns()

    def _is_forbidden_host(self: "ServiceUrlPolicyMixinProtocol", host: str) -> bool:
        return self._url_policy().is_forbidden_host(host)

    def is_forbidden_url(self: "ServiceUrlPolicyMixinProtocol", url: str) -> bool:
        return self._url_policy().is_forbidden_url(url)

    def _allowed_discovery_hosts(self: "ServiceUrlPolicyMixinProtocol") -> List[str]:
        return self._url_policy().allowed_discovery_hosts()

    def is_discovery_url_allowed(self: "ServiceUrlPolicyMixinProtocol", url: str) -> bool:
        return self._url_policy().is_discovery_url_allowed(url)

    def is_video_url(self, url: str) -> bool:
        return self._url_policy().is_video_url(url)

from hawki_crawler.crawler.assets.asset_service_mixin import ServiceParseAssetsMixin
from hawki_crawler.crawler.communication.progress_mixin import ServiceProgressMixin
from hawki_crawler.crawler.core.execution.execution_mixin import ServiceCrawlExecutionMixin
from hawki_crawler.crawler.core.runtime.init_mixin import ServiceInitMixin
from hawki_crawler.crawler.core.runtime.runtime_mixin import ServiceCrawlRuntimeMixin
from hawki_crawler.crawler.parsing.content_mixin import ServiceParseContentMixin
from hawki_crawler.crawler.parsing.date_language_mixin import ServiceDateLangMixin
from hawki_crawler.crawler.policies.url_policy_mixin import ServiceUrlPolicyMixin
from hawki_crawler.crawler.sitemap.sitemap_mixin import ServiceSitemapMixin
from hawki_crawler.crawler.storage.storage_mixin import ServiceStorageMixin


class CrawlerService(
    ServiceInitMixin,
    ServiceStorageMixin,
    ServiceUrlPolicyMixin,
    ServiceSitemapMixin,
    ServiceProgressMixin,
    ServiceDateLangMixin,
    ServiceParseAssetsMixin,
    ServiceParseContentMixin,
    ServiceCrawlRuntimeMixin,
    ServiceCrawlExecutionMixin
):
    """Main crawler service handling all crawling operations."""

    pass

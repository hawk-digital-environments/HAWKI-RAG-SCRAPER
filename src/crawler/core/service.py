from hawki_crawler.crawler.assets.mixin import ServiceParseAssetsMixin
from hawki_crawler.crawler.communication.progress_mixin import ServiceProgressMixin
from hawki_crawler.crawler.core.execution.mixin import ServiceCrawlExecutionMixin
from hawki_crawler.crawler.core.runtime.init_mixin import ServiceInitMixin
from hawki_crawler.crawler.core.runtime.mixin import ServiceCrawlRuntimeMixin
from hawki_crawler.crawler.parsing.content_mixin import ServiceParseContentMixin
from hawki_crawler.crawler.parsing.date_language_mixin import ServiceDateLangMixin
from hawki_crawler.crawler.policies.mixin import ServiceUrlPolicyMixin
from hawki_crawler.crawler.sitemap.mixin import ServiceSitemapMixin
from hawki_crawler.crawler.storage.mixin import ServiceStorageMixin


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

from hawki_crawler.crawler.core.service_init import ServiceInitMixin
from hawki_crawler.crawler.core.service_storage import ServiceStorageMixin
from hawki_crawler.crawler.core.service_url_policy import ServiceUrlPolicyMixin
from hawki_crawler.crawler.core.service_sitemap import ServiceSitemapMixin
from hawki_crawler.crawler.core.service_progress import ServiceProgressMixin
from hawki_crawler.crawler.core.service_date_lang import ServiceDateLangMixin
from hawki_crawler.crawler.core.service_parse_assets import ServiceParseAssetsMixin
from hawki_crawler.crawler.core.service_parse_content import ServiceParseContentMixin
from hawki_crawler.crawler.core.service_crawl_runtime import ServiceCrawlRuntimeMixin
from hawki_crawler.crawler.core.service_crawl_execution import ServiceCrawlExecutionMixin


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

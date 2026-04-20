from src.crawler.core.service_init import ServiceInitMixin
from src.crawler.core.service_url_policy import ServiceUrlPolicyMixin
from src.crawler.core.service_sitemap import ServiceSitemapMixin
from src.crawler.core.service_progress import ServiceProgressMixin
from src.crawler.core.service_date_lang import ServiceDateLangMixin
from src.crawler.core.service_parse_assets import ServiceParseAssetsMixin
from src.crawler.core.service_parse_content import ServiceParseContentMixin
from src.crawler.core.service_crawl_runtime import ServiceCrawlRuntimeMixin
from src.crawler.core.service_crawl_execution import ServiceCrawlExecutionMixin


class CrawlerService(
    ServiceInitMixin,
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

from src.crawler.core.service_init import ServiceInitMixin
from src.crawler.core.service_utils import ServiceUtilsMixin
from src.crawler.core.service_progress import ServiceProgressMixin
from src.crawler.core.service_date_lang import ServiceDateLangMixin
from src.crawler.core.service_parse import ServiceParseMixin
from src.crawler.core.service_crawl import ServiceCrawlMixin


class CrawlerService(
    ServiceInitMixin,
    ServiceUtilsMixin,
    ServiceProgressMixin,
    ServiceDateLangMixin,
    ServiceParseMixin,
    ServiceCrawlMixin
):
    """Main crawler service handling all crawling operations."""

    pass

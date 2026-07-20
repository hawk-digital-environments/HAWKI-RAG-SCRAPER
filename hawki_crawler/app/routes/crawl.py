from fastapi import APIRouter

from hawki_crawler.app import job_lifecycle
from hawki_crawler.crawler.models import CrawlConfig, CrawlResponse

router = APIRouter()


@router.post("/crawl", response_model=CrawlResponse)
async def crawl(config: CrawlConfig):
    """
    Submit a crawl job.
    """
    return job_lifecycle.submit_crawl_job(config)

from fastapi import APIRouter, HTTPException

from hawki_crawler.app import job_lifecycle
from hawki_crawler.crawler.models import CrawlConfig, CrawlResponse

router = APIRouter()


@router.post("/crawl", response_model=CrawlResponse)
async def crawl(config: CrawlConfig):
    """
    Submit a crawl job.
    """
    try:
        return job_lifecycle.submit_crawl_job(config)
    except OverflowError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

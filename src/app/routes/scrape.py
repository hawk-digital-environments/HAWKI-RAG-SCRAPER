import time

from fastapi import APIRouter

from hawki_crawler.app.quick_scrape import extract_page_content
from hawki_crawler.crawler.models import QuickScrapeRequest, QuickScrapeResponse

router = APIRouter()


@router.post("/scrape", response_model=QuickScrapeResponse)
async def quick_scrape(request: QuickScrapeRequest):
    """
    Temporary scraping endpoint - returns data directly without storage.
    """
    start_time = time.time()

    try:
        data = await extract_page_content(
            str(request.url),
            skip_images=request.skip_images,
            date_selector=request.date_selector if request.extract_date else None
        )

        extraction_time = time.time() - start_time

        return QuickScrapeResponse(
            url=str(request.url),
            success=True,
            title=data['title'],
            content=data['content'],
            images=data['images'],
            meta_image=data['meta_image'],
            date=data['date'],
            extraction_time_seconds=round(extraction_time, 2)
        )

    except Exception as e:
        extraction_time = time.time() - start_time

        return QuickScrapeResponse(
            url=str(request.url),
            success=False,
            error=str(e),
            extraction_time_seconds=round(extraction_time, 2)
        )

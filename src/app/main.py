import os
import time
import logging
import sys
from contextlib import asynccontextmanager
from typing import Dict
from urllib.parse import urljoin
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from bs4 import BeautifulSoup
import html2text

from crawl4ai import AsyncWebCrawler
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig, CacheMode

from hawki_crawler.app import job_lifecycle
from hawki_crawler.app.routes.health import router as health_router
from hawki_crawler.app.routes.jobs import router as jobs_router
from hawki_crawler.crawler.models import CrawlConfig, CrawlResponse, QuickScrapeRequest, QuickScrapeResponse
from hawki_crawler.common.logging_setup import configure_logging

# Configure logging for Docker with env-driven level/format.
configure_logging()
logger = logging.getLogger("crawler.api")


# Force unbuffered output for Docker
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)


def _log_startup_configuration() -> None:
    """Log startup configuration."""
    logger.info("=" * 60)
    logger.info("Crawl4AI Service Starting...")
    logger.info("=" * 60)
    logger.info(f"Communication Method: {os.getenv('COMMUNICATION_METHOD', 'none')}")
    logger.info(f"Communication Enabled: {os.getenv('COMMUNICATION_ENABLED', 'true')}")

    comm_method = os.getenv('COMMUNICATION_METHOD', 'none').lower()
    if comm_method == 'rabbitmq':
        logger.info(f"RabbitMQ Host: {os.getenv('RABBITMQ_HOST', 'localhost')}")
        logger.info(f"RabbitMQ Port: {os.getenv('RABBITMQ_PORT', '5672')}")
        logger.info(f"RabbitMQ User: {os.getenv('RABBITMQ_USER', 'guest')}")
        logger.info(f"RabbitMQ Exchange: {os.getenv('RABBITMQ_EXCHANGE', 'scrape-events')}")

    logger.info(f"Data Path: {os.getenv('DATA_PATH', '/app/data/jobs')}")
    logger.info("=" * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _log_startup_configuration()
    try:
        yield
    finally:
        await job_lifecycle.cancel_active_crawl_tasks()
        logger.info("Crawl4AI Service shutdown complete")


app = FastAPI(
    title="Crawl4AI API",
    description="FastAPI interface for crawl4ai library with sitemap support and URL discovery",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(jobs_router)


async def extract_page_content(url: str, skip_images: bool = False, date_selector: str = None) -> Dict:
    """
    Temporary extraction function for quick scraping without storage.

    This function:
    - Fetches and renders the page using crawl4ai
    - Extracts content, images, title, and metadata
    - Returns data directly without saving to disk

    Args:
        url: URL to scrape
        skip_images: Whether to skip image extraction
        date_selector: Optional CSS selector for date extraction

    Returns:
        Dictionary with extracted data
    """
    browser_config = BrowserConfig(
        headless=True,
        verbose=False
    )

    wait_until = os.getenv("CRAWL_WAIT_UNTIL", "domcontentloaded")
    page_timeout_ms = int(os.getenv("CRAWL_PAGE_TIMEOUT_MS", "90000"))

    run_config = CrawlerRunConfig(
        word_count_threshold=0,  # No threshold - capture all content
        exclude_external_links=False,
        process_iframes=False,
        remove_overlay_elements=True,
        cache_mode=CacheMode.BYPASS,
        wait_until=wait_until,
        page_timeout=page_timeout_ms,
        delay_before_return_html=5.0
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=run_config)

        if not result.success:
            raise Exception(f"Failed to crawl {url}: {result.error_message}")

        # Extract markdown content (with fallbacks)
        markdown_content = result.markdown

        if not markdown_content or len(markdown_content.strip()) <= 1:
            # Try html2text first
            h = html2text.HTML2Text()
            h.ignore_links = False
            h.body_width = 0
            h.ignore_images = False
            markdown_content = h.handle(result.html)

            # If html2text also fails, use BeautifulSoup
            if not markdown_content or len(markdown_content.strip()) <= 1:
                html_to_parse = result.fit_html if hasattr(result, 'fit_html') and result.fit_html else \
                              result.cleaned_html if hasattr(result, 'cleaned_html') and result.cleaned_html else \
                              result.html
                soup_temp = BeautifulSoup(html_to_parse, 'html.parser')

                main_content = soup_temp.find('main') or soup_temp.find('article') or soup_temp.find('body')
                if main_content:
                    for script in main_content(['script', 'style', 'nav', 'header', 'footer']):
                        script.decompose()

                    markdown_content = main_content.get_text(separator='\n', strip=True)
                    lines = [line.strip() for line in markdown_content.split('\n') if line.strip()]
                    markdown_content = '\n\n'.join(lines)

        # Parse HTML for additional data
        soup = BeautifulSoup(result.html, 'html.parser')

        # Extract title
        title = None
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.text.strip()

        # Extract meta image
        meta_img_url = None
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            meta_img_url = og_image['content']

        # Extract date if selector provided
        date_text = None
        if date_selector:
            date_elements = soup.select(date_selector)
            for elem in date_elements:
                date_text = elem.get('content') or elem.get('datetime') or elem.text
                if date_text:
                    date_text = date_text.strip()
                    break

        # Extract images (URLs only, no download)
        images = []
        if not skip_images:
            # Try crawl4ai's media extraction
            for img in (result.media or {}).get('images', []):
                img_src = img.get('src', '')
                if img_src:
                    absolute_img_url = urljoin(url, img_src)
                    images.append(absolute_img_url)

            # If crawl4ai found no images, fallback to BeautifulSoup
            if len(images) == 0:
                img_tags = soup.find_all('img')
                for img_tag in img_tags:
                    img_src = img_tag.get('src') or img_tag.get('data-src') or img_tag.get('data-lazy-src')
                    if img_src and img_src.startswith(('http', '/')):
                        if not img_src.startswith('data:'):
                            absolute_img_url = urljoin(url, img_src)
                            if absolute_img_url not in images:
                                images.append(absolute_img_url)

        return {
            'title': title,
            'content': markdown_content if markdown_content else "",
            'images': images,
            'meta_image': meta_img_url,
            'date': date_text
        }


@app.post("/crawl", response_model=CrawlResponse)
async def crawl(config: CrawlConfig):
    """
    Submit a crawl job

    Parameters:
    - job_id: Unique identifier for the crawl job (required)
    - url: The starting URL to crawl (required)
    - max_pages: Maximum number of pages to crawl (default: 100)
    - output_dir: Directory to store crawled data (default: "output")
    - label: Label for this crawl job (auto-generated if not provided)
    - skip_images: Skip downloading images (default: False)
    - image_exceptions: Comma-separated CSS selectors for elements to exclude from image scraping
    - date_selector: CSS selector for date elements
    - max_concurrency: Maximum number of parallel requests (default: 4)
    - max_rpm: Maximum requests per minute (default: 60)
    - request_delay: Delay between requests in milliseconds (overrides RPM)
    - discovery_mode: Discover URLs inside the given page (default: False)
    - sitemap_only: Crawl only sitemap entries (no discovery and no non-sitemap URLs)
    - rescrape_failed: Rescrape only failed URLs from existing job state (default: False)
    - min_word_count: Minimum word count for content quality (0 disables filter)
    - max_link_density: Max link density before content is treated as navigation
    - max_link_density_words: Max words to consider for link density filtering

    Returns:
    - job_id: Unique identifier for the crawl job
    - event: Event type (e.g., "job_submitted")
    - data: Object with status and message
    - timestamp: ISO-8601 timestamp
    """
    return job_lifecycle.submit_crawl_job(config)


@app.post("/scrape", response_model=QuickScrapeResponse)
async def quick_scrape(request: QuickScrapeRequest):
    """
    Temporary scraping endpoint - returns data directly without storage.

    This endpoint:
    - Fetches a single URL and extracts content
    - Returns all data directly in the response (no files saved)
    - Does NOT download images (returns URLs only)
    - Perfect for previewing content or quick data extraction

    Parameters:
    - url: The URL to scrape (required)
    - skip_images: Skip image extraction (default: False)
    - extract_date: Attempt to extract publication date (default: False)
    - date_selector: CSS selector for date elements (optional)

    Returns:
    - url: The scraped URL
    - success: Whether extraction succeeded
    - title: Page title
    - content: Extracted markdown content
    - images: List of image URLs (not downloaded)
    - meta_image: OpenGraph meta image URL
    - date: Extracted date (if extract_date=True)
    - extraction_time_seconds: Time taken to scrape
    - error: Error message if failed

    Example:
    ```bash
    curl -X POST http://localhost:8004/scrape \\
      -H 'Content-Type: application/json' \\
      -d '{"url": "https://example.com"}'
    ```
    """
    start_time = time.time()

    try:
        # Extract content
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

from pydantic import BaseModel, Field, HttpUrl
from typing import Optional
from datetime import datetime


class CrawlConfig(BaseModel):
    """Configuration for crawl job"""
    job_id: str = Field(..., description="Unique identifier for the crawl job")
    url: HttpUrl = Field(..., description="The starting URL to crawl")
    max_pages: int = Field(default=100, ge=0, description="Maximum number of pages to crawl (0 = unlimited)")
    output_dir: str = Field(default="output", description="Directory to store crawled data")
    label: Optional[str] = Field(default=None, description="Label for this crawl job (auto-generated if not provided)")
    skip_images: bool = Field(default=False, description="Skip downloading images")
    image_exceptions: Optional[str] = Field(default=None, description="Comma-separated CSS selectors for elements to exclude from image scraping")
    date_selector: Optional[str] = Field(default=None, description="CSS selector for date elements")
    max_concurrency: int = Field(default=4, ge=1, le=20, description="Maximum number of parallel requests")
    max_rpm: int = Field(default=60, ge=1, description="Maximum requests per minute")
    request_delay: Optional[int] = Field(default=None, ge=0, description="Delay between requests in milliseconds")
    discovery_mode: bool = Field(default=False, description="Discover URLs inside the given page")
    sitemap_only: bool = Field(
        default=False,
        description="Crawl only sitemap entries (no discovery and no non-sitemap URLs)",
    )
    sitemap: bool = Field(default=False, alias="hawk_sitemap", description="Pre-scrape the sitemap before crawling")
    rescrape_failed: bool = Field(default=False, description="Rescrape failed URLs from existing job state")
    min_word_count: int = Field(default=20, ge=0, description="Minimum word count for content quality (0 disables filter)")
    max_link_density: float = Field(default=0.4, ge=0.0, le=1.0, description="Max link density before content is treated as navigation")
    max_link_density_words: int = Field(default=200, ge=0, description="Max words to consider for link density filtering")
    sitemap_base: Optional[str] = Field(default=None, description="Base URL for the sitemap pages")
    sitemap_output: Optional[str] = Field(default=None, description="Output path for the scraped sitemap JSON")
    sitemap_start_page: Optional[int] = Field(default=None, description="Starting page for sitemap pagination")
    sitemap_pages: Optional[int] = Field(default=None, description="Number of sitemap pages to scrape")
    wait_until: str = Field(default="domcontentloaded", description="Playwright waitUntil condition")
    page_timeout_ms: int = Field(default=90000, ge=1, description="Page timeout in milliseconds")

    class Config:
        allow_population_by_field_name = True


class CrawlStatus(BaseModel):
    """Status response for crawl job"""
    job_id: str
    status: str
    message: str
    pages_crawled: int = 0
    total_pages: int = 0
    output_directory: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None


class CrawlResponse(BaseModel):
    """
    Response for crawl job submission.

    Structure matches event_emitter format for consistency:
    - event: The type of event (e.g., "job_submitted")
    - data: Object containing status, message, and other metadata
    - timestamp: ISO-8601 timestamp
    """
    job_id: str
    event: str
    data: dict
    timestamp: str


class QuickScrapeRequest(BaseModel):
    """Request for temporary scraping without storage"""
    url: HttpUrl = Field(..., description="The URL to scrape")
    skip_images: bool = Field(default=False, description="Skip extracting images")
    extract_date: bool = Field(default=False, description="Attempt to extract publication date")
    date_selector: Optional[str] = Field(default=None, description="CSS selector for date elements")


class QuickScrapeResponse(BaseModel):
    """Response for temporary scrape with data directly in response"""
    url: str
    success: bool
    title: Optional[str] = None
    content: Optional[str] = None
    images: list = []
    meta_image: Optional[str] = None
    date: Optional[str] = None
    error: Optional[str] = None
    extraction_time_seconds: float

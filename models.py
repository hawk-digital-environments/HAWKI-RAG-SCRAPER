from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List
from datetime import datetime


class CrawlConfig(BaseModel):
    """Configuration for crawl job"""
    url: HttpUrl = Field(..., description="The starting URL to crawl")
    max_pages: int = Field(default=100, ge=1, description="Maximum number of pages to crawl")
    output_dir: str = Field(default="output", description="Directory to store crawled data")
    label: Optional[str] = Field(default=None, description="Label for this crawl job (auto-generated if not provided)")
    skip_images: bool = Field(default=False, description="Skip downloading images")
    image_exceptions: Optional[str] = Field(default=None, description="Comma-separated CSS selectors for elements to exclude from image scraping")
    date_selector: Optional[str] = Field(default=None, description="CSS selector for date elements")
    max_concurrency: int = Field(default=4, ge=1, le=20, description="Maximum number of parallel requests")
    max_rpm: int = Field(default=60, ge=1, description="Maximum requests per minute")
    request_delay: Optional[int] = Field(default=None, ge=0, description="Delay between requests in milliseconds")
    discovery_mode: bool = Field(default=False, description="Discover URLs inside the given page")


class PageData(BaseModel):
    """Data structure for a single crawled page"""
    title: List[str]
    page_url: List[str]
    meta_img_url: List[str]
    images: List[str]
    date: List[str]


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
    """Response for crawl job submission"""
    job_id: str
    message: str
    status: str

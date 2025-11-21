import uuid
from datetime import datetime
from typing import Dict
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from models import CrawlConfig, CrawlResponse, CrawlStatus
from crawler_service import CrawlerService

app = FastAPI(
    title="Crawl4AI API",
    description="FastAPI interface for crawl4ai library with sitemap support and URL discovery",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store job statuses
jobs: Dict[str, CrawlStatus] = {}


async def run_crawl_job(job_id: str, config: CrawlConfig):
    """Background task to run crawl job"""
    try:
        jobs[job_id].status = "running"
        jobs[job_id].message = "Crawling in progress..."

        crawler = CrawlerService(config)
        result = await crawler.crawl()

        jobs[job_id].status = "completed"
        jobs[job_id].message = "Crawl completed successfully"
        jobs[job_id].pages_crawled = result['pages_crawled']
        jobs[job_id].total_pages = result['pages_crawled']
        jobs[job_id].output_directory = result['output_directory']
        jobs[job_id].completed_at = datetime.now()

    except Exception as e:
        jobs[job_id].status = "failed"
        jobs[job_id].message = f"Crawl failed: {str(e)}"
        jobs[job_id].completed_at = datetime.now()


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Crawl4AI API is running",
        "version": "1.0.0",
        "endpoints": {
            "/crawl": "POST - Submit a crawl job",
            "/status/{job_id}": "GET - Check crawl job status",
            "/jobs": "GET - List all jobs",
            "/docs": "GET - API documentation"
        }
    }


@app.post("/crawl", response_model=CrawlResponse)
async def crawl(config: CrawlConfig, background_tasks: BackgroundTasks):
    """
    Submit a crawl job

    Parameters:
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

    Returns:
    - job_id: Unique identifier for the crawl job
    - message: Status message
    - status: Job status
    """
    job_id = str(uuid.uuid4())

    # Create job status
    job_status = CrawlStatus(
        job_id=job_id,
        status="pending",
        message="Crawl job submitted",
        started_at=datetime.now()
    )
    jobs[job_id] = job_status

    # Add background task
    background_tasks.add_task(run_crawl_job, job_id, config)

    return CrawlResponse(
        job_id=job_id,
        message="Crawl job submitted successfully",
        status="pending"
    )


@app.get("/status/{job_id}", response_model=CrawlStatus)
async def get_status(job_id: str):
    """
    Get the status of a crawl job

    Parameters:
    - job_id: The unique identifier of the crawl job

    Returns:
    - Job status information including progress and output directory
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    return jobs[job_id]


@app.get("/jobs")
async def list_jobs():
    """
    List all crawl jobs

    Returns:
    - Dictionary of all jobs with their statuses
    """
    return {
        "total_jobs": len(jobs),
        "jobs": jobs
    }


@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    """
    Delete a job from the jobs list

    Parameters:
    - job_id: The unique identifier of the crawl job to delete

    Returns:
    - Success message
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    del jobs[job_id]
    return {"message": f"Job {job_id} deleted successfully"}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

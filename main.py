import uuid
import os
from datetime import datetime
from typing import Dict
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from models import CrawlConfig, CrawlResponse, CrawlStatus
from crawler_service import CrawlerService
from services import EventEmitter, JobStateManager, StorageManager

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
    """
    Background task to run crawl job.

    This function integrates the service layer components:
    - EventEmitter: For real-time progress updates via WebSocket
    - JobStateManager: For persistent state tracking
    - StorageManager: For consistent file I/O operations
    """
    # Initialize service layer components
    websocket_url = os.getenv("WEBSOCKET_URL", None)  # e.g., "ws://laravel-app:6001"
    base_path = os.getenv("DATA_PATH", "/app/data/jobs")

    event_emitter = EventEmitter(job_id, websocket_url=websocket_url)
    job_state_manager = JobStateManager(job_id, base_path=base_path)
    storage_manager = StorageManager(job_id, base_path=base_path)

    try:
        # Initialize state manager (creates job directory and initial state file)
        await job_state_manager.initialize()

        # Connect event emitter (if WebSocket URL is configured)
        if websocket_url:
            await event_emitter.connect()

        jobs[job_id].status = "running"
        jobs[job_id].message = "Crawling in progress..."

        # Create crawler with service layer integration
        crawler = CrawlerService(
            config,
            job_id=job_id,
            event_emitter=event_emitter,
            job_state_manager=job_state_manager,
            storage_manager=storage_manager
        )

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

    finally:
        # Close event emitter connection
        if event_emitter:
            await event_emitter.close()


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
            "/jobs/{job_id}/files": "GET - List files for a job",
            "/jobs/{job_id}/files/{file_path}": "GET - Download a specific file",
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


@app.get("/jobs/{job_id}/files")
async def list_job_files(job_id: str):
    """
    List all files for a specific job.

    This endpoint returns a JSON list of all files stored in the job's directory,
    allowing Laravel or other clients to discover what was scraped.

    Parameters:
    - job_id: The unique identifier of the crawl job

    Returns:
    - List of file paths with metadata (name, path, size, type)
    """
    base_path = os.getenv("DATA_PATH", "/app/data/jobs")
    storage_manager = StorageManager(job_id, base_path=base_path)

    # Check if job directory exists
    if not storage_manager.get_job_directory().exists():
        raise HTTPException(status_code=404, detail="Job not found or no data available")

    # Get list of all files
    files = storage_manager.list_files(relative=True)

    # Get detailed info for each file
    files_info = []
    for file_path in files:
        info = storage_manager.get_file_info(file_path)
        if info:
            files_info.append(info)

    return {
        "job_id": job_id,
        "total_files": len(files_info),
        "files": files_info
    }


@app.get("/jobs/{job_id}/files/{file_path:path}")
async def download_job_file(job_id: str, file_path: str):
    """
    Download a specific file from a job's directory.

    This endpoint streams the requested file back to the client.
    Used by Laravel to retrieve scraped content, images, or metadata.

    Parameters:
    - job_id: The unique identifier of the crawl job
    - file_path: Relative path to the file within the job directory

    Returns:
    - File content as a streaming response
    """
    base_path = os.getenv("DATA_PATH", "/app/data/jobs")
    storage_manager = StorageManager(job_id, base_path=base_path)

    # Get the file path (includes security check)
    absolute_path = storage_manager.get_file_path(file_path)

    if not absolute_path:
        raise HTTPException(status_code=404, detail="File not found")

    # Get file info for content type
    file_info = storage_manager.get_file_info(file_path)
    media_type = file_info['type'] if file_info else 'application/octet-stream'

    # Stream the file
    return FileResponse(
        path=str(absolute_path),
        media_type=media_type,
        filename=absolute_path.name
    )


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

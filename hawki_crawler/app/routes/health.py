from datetime import datetime

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Crawl4AI API is running",
        "version": "1.0.0",
        "endpoints": {
            "/crawl": "POST - Submit a crawl job",
            "/scrape": "POST - Quick scrape (returns data directly, no storage)",
            "/status/{job_id}": "GET - Check crawl job status",
            "/jobs": "GET - List all jobs",
            "/jobs/{job_id}/files": "GET - List files for a job",
            "/jobs/{job_id}/files/{file_path}": "GET - Download a specific file",
            "/docs": "GET - API documentation"
        }
    }


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }

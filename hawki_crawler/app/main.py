import os
import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hawki_crawler.app import job_lifecycle
from hawki_crawler.app.routes.crawl import router as crawl_router
from hawki_crawler.app.routes.health import router as health_router
from hawki_crawler.app.routes.jobs import router as jobs_router
from hawki_crawler.app.routes.scrape import router as scrape_router
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
    logger.info(f"Data Path: {os.getenv('DATA_PATH', '/var/www/html/shared')}")
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
app.include_router(crawl_router)
app.include_router(scrape_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

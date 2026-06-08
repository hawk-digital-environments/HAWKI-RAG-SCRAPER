import asyncio
import logging
import os
import traceback
from contextlib import suppress
from datetime import datetime
from typing import Dict

from hawki_crawler.crawler.communication.factory import CommunicationFactory
from hawki_crawler.crawler.core.service import CrawlerService
from hawki_crawler.crawler.models import CrawlConfig, CrawlResponse, CrawlStatus
from hawki_crawler.crawler.state.job_state import JobState
from hawki_crawler.crawler.storage.storage_manager import StorageManager

logger = logging.getLogger("crawler.api")

# Store job statuses
jobs: Dict[str, CrawlStatus] = {}
# Track running tasks for cancellation
tasks: Dict[str, asyncio.Task] = {}
# Track pause controls and state objects for running jobs
pause_events: Dict[str, asyncio.Event] = {}
job_states: Dict[str, JobState] = {}


class JobNotFoundError(Exception):
    """Raised when an operation targets an unknown job."""


class JobNotRunningError(Exception):
    """Raised when an operation requires an active job task."""


async def run_crawl_job(job_id: str, config: CrawlConfig):
    """
    Background task to run crawl job.

    Integrates the service layer components:
    - CommunicationFactory: optional message queue events
    - JobState: Persistent state tracking
    - StorageManager: File I/O operations
    """
    base_path = os.getenv("DATA_PATH", "/var/www/html/shared")
    communication_method = os.getenv("COMMUNICATION_METHOD", "none")

    logger.info("=" * 60)
    logger.info(f"[Job {job_id}] Starting crawl job")
    logger.info(f"[Job {job_id}] Target URL: {config.url}")
    logger.info(f"[Job {job_id}] Max Pages: {config.max_pages}")
    logger.info(f"[Job {job_id}] Communication Method: {communication_method}")
    logger.info("=" * 60)

    communication_service = CommunicationFactory.create(job_id)
    job_state = JobState(job_id, base_path=base_path)
    pause_event = pause_events.setdefault(job_id, asyncio.Event())
    pause_event.set()
    storage_manager = StorageManager(job_id, base_path=base_path)

    def _progress_total(snapshot) -> int:
        if config.max_pages > 0:
            return config.max_pages
        return snapshot.total_urls or (snapshot.completed_urls + snapshot.failed_urls)

    async def _sync_job_progress(poll_interval: float = 1.0):
        while True:
            snapshot = await job_state.get_snapshot()
            if job_id in jobs:
                jobs[job_id].pages_crawled = snapshot.completed_urls
                jobs[job_id].total_pages = _progress_total(snapshot)
                jobs[job_id].output_directory = snapshot.output_directory or jobs[job_id].output_directory
            await asyncio.sleep(poll_interval)

    sync_task = None
    crawler = None
    try:
        logger.info(f"[Job {job_id}] Initializing state manager...")
        # Initialize state manager (creates job directory and initial state file)
        await job_state.initialize()
        job_states[job_id] = job_state
        logger.info(f"[Job {job_id}] State manager initialized")
        sync_task = asyncio.create_task(_sync_job_progress())

        # Connect to communication service (optional)
        if communication_service:
            try:
                logger.info(f"[Job {job_id}] Attempting to connect to {communication_method}...")
                connected = await communication_service.connect()
                if connected:
                    logger.info(f"[Job {job_id}] Successfully connected to {communication_method}")
                else:
                    logger.warning(f"[Job {job_id}] {communication_method} connection failed. Continuing without real-time event updates.")
            except Exception as comm_error:
                logger.error(f"[Job {job_id}] {communication_method} connection error: {comm_error}. Continuing without real-time event updates.")
                logger.error(traceback.format_exc())
        else:
            logger.info(f"[Job {job_id}] No communication service configured (communication disabled or failed to initialize)")

        logger.info(f"[Job {job_id}] Communication setup complete. Starting crawler...")

        jobs[job_id].status = "running"
        jobs[job_id].message = "Crawling in progress..."

        # Create crawler with service layer integration
        logger.info(f"[{job_id}] Creating CrawlerService...")
        crawler = CrawlerService(
            config,
            job_id=job_id,
            communication_service=communication_service,
            job_state=job_state,
            storage_manager=storage_manager,
            pause_event=pause_event
        )

        logger.info(f"[{job_id}] CrawlerService created. Starting crawl...")
        result = await crawler.crawl()
        logger.info(f"[{job_id}] Crawl completed successfully!")

        jobs[job_id].status = "completed"
        jobs[job_id].message = "Crawl completed successfully"
        final_snapshot = await job_state.get_snapshot()
        jobs[job_id].pages_crawled = final_snapshot.completed_urls
        jobs[job_id].total_pages = _progress_total(final_snapshot)
        jobs[job_id].output_directory = result['output_directory']
        jobs[job_id].completed_at = datetime.now()

    except asyncio.CancelledError:
        jobs[job_id].status = "cancelled"
        jobs[job_id].message = "Crawl cancelled"
        jobs[job_id].completed_at = datetime.now()
        await job_state.set_status("cancelled")
        # Propagate cancellation after cleanup
        raise
    except Exception as e:
        logger.exception("run_crawl_job failed", extra={"job_id": job_id, "error": str(e)})
        jobs[job_id].status = "failed"
        jobs[job_id].message = f"Crawl failed: {str(e)}"
        jobs[job_id].completed_at = datetime.now()

    finally:
        if sync_task:
            sync_task.cancel()
            try:
                await sync_task
            except asyncio.CancelledError:
                pass
        # Close communication connection
        if communication_service and hasattr(communication_service, "disconnect"):
            try:
                await communication_service.disconnect()
            except Exception:
                pass
        if crawler and hasattr(crawler, "file_event_publisher") and crawler.file_event_publisher:
            try:
                await crawler.file_event_publisher.close()
            except Exception:
                pass
        pause_events.pop(job_id, None)
        job_states.pop(job_id, None)
        tasks.pop(job_id, None)


def _log_crawl_task_finished(job_id: str, task: asyncio.Task) -> None:
    if task.cancelled():
        logger.info(
            "crawl job finished",
            extra={"job_id": job_id, "status": "cancelled", "error": None},
        )
        return

    error = task.exception()
    job = jobs.get(job_id)
    status = job.status if job else ("failed" if error else "completed")
    logger.info(
        "crawl job finished",
        extra={
            "job_id": job_id,
            "status": status,
            "error": str(error) if error else None,
        },
    )


def submit_crawl_job(config: CrawlConfig) -> CrawlResponse:
    job_id = config.job_id

    job_status = CrawlStatus(
        job_id=job_id,
        status="pending",
        message="Crawl job submitted",
        total_pages=config.max_pages if config.max_pages > 0 else 0,
        started_at=datetime.now()
    )
    jobs[job_id] = job_status

    logger.info("crawl job queued", extra={"job_id": job_id, "url": str(config.url)})

    task = asyncio.create_task(run_crawl_job(job_id, config))
    task.add_done_callback(lambda t: _log_crawl_task_finished(job_id, t))
    tasks[job_id] = task

    return CrawlResponse(
        job_id=job_id,
        event="job_submitted",
        data={
            "status": "pending",
            "message": "Crawl job submitted successfully"
        },
        timestamp=datetime.utcnow().isoformat() + "Z"
    )


def get_job_status(job_id: str) -> CrawlStatus | None:
    return jobs.get(job_id)


def list_jobs() -> Dict:
    return {
        "total_jobs": len(jobs),
        "jobs": jobs
    }


def delete_job(job_id: str) -> bool:
    if job_id not in jobs:
        return False

    del jobs[job_id]
    return True


def _get_running_task(job_id: str) -> asyncio.Task:
    if job_id not in jobs:
        raise JobNotFoundError(job_id)

    task = tasks.get(job_id)
    if not task or task.done():
        raise JobNotRunningError(job_id)

    return task


def cancel_job(job_id: str) -> Dict[str, object]:
    task = _get_running_task(job_id)
    task.cancel()
    return {
        "success": True,
        "message": f"Cancel requested for job {job_id}"
    }


async def pause_job(job_id: str) -> Dict[str, object]:
    _get_running_task(job_id)

    event = pause_events.setdefault(job_id, asyncio.Event())
    event.clear()
    jobs[job_id].status = "paused"
    jobs[job_id].message = "Crawl paused"

    state = job_states.get(job_id)
    if state:
        await state.set_status("paused")

    return {
        "success": True,
        "message": f"Pause requested for job {job_id}"
    }


async def resume_job(job_id: str) -> Dict[str, object]:
    _get_running_task(job_id)

    event = pause_events.setdefault(job_id, asyncio.Event())
    event.set()
    jobs[job_id].status = "running"
    jobs[job_id].message = "Crawling in progress..."

    state = job_states.get(job_id)
    if state:
        await state.set_status("running")

    return {
        "success": True,
        "message": f"Resume requested for job {job_id}"
    }


async def cancel_active_crawl_tasks() -> None:
    """Cancel active crawl jobs during application shutdown."""
    active_tasks = [(job_id, task) for job_id, task in tasks.items() if not task.done()]
    if not active_tasks:
        return

    logger.info("Cancelling active crawl jobs", extra={"active_jobs": len(active_tasks)})
    for pause_event in pause_events.values():
        pause_event.set()

    for job_id, task in active_tasks:
        job = jobs.get(job_id)
        if job:
            job.status = "cancelled"
            job.message = "Crawl cancelled during service shutdown"
            job.completed_at = datetime.now()

        state = job_states.get(job_id)
        if state:
            with suppress(Exception):
                await state.set_status("cancelled")

        task.cancel()

    results = await asyncio.gather(
        *(task for _job_id, task in active_tasks),
        return_exceptions=True,
    )

    for (job_id, _task), result in zip(active_tasks, results):
        if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
            logger.warning(
                "crawl job raised during shutdown",
                extra={"job_id": job_id, "error": str(result)},
            )
        tasks.pop(job_id, None)
        pause_events.pop(job_id, None)
        job_states.pop(job_id, None)

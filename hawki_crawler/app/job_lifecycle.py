import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict

from hawki_crawler.crawler.core.service import CrawlerService
from hawki_crawler.crawler.models import CrawlConfig, CrawlResponse, CrawlStatus
from hawki_crawler.crawler.state.job_state import JobState
from hawki_crawler.crawler.storage.storage_manager import StorageManager
from hawki_crawler.runtime.scope import JobScope, current_scope, install_task_tracking
from hawki_crawler.runtime.store import RuntimeStore, now

logger = logging.getLogger("crawler.api")

# Store job statuses
jobs: Dict[str, CrawlStatus] = {}
# Track running tasks for cancellation
tasks: Dict[str, asyncio.Task] = {}
# Track pause controls and state objects for running jobs
pause_events: Dict[str, asyncio.Event] = {}
job_states: Dict[str, JobState] = {}
_stores = {}
_executions = {}
_scopes = {}


def runtime_store():
    root = str(Path(os.getenv("DATA_PATH", "/var/www/html/shared")).resolve())
    if root not in _stores:
        _stores[root] = RuntimeStore(root)
    return _stores[root]


def close_runtime_stores():
    for store in _stores.values():
        store.close()
    _stores.clear()


async def _run_managed(config, store):
    job_id = config.job_id
    scope = JobScope(Path(store.get(job_id)["output_directory"]), store.path(job_id))
    _scopes[job_id] = scope
    token = current_scope.set(scope)
    try:
        if store.get(job_id)["cancel_requested"]:
            jobs[job_id].status = "cancelled"
            jobs[job_id].message = "Cancelled before execution"
        else:
            store.update(job_id, status="running", started_at=now())
            execution = asyncio.create_task(run_crawl_job(job_id, config))
            _executions[job_id] = execution
            try:
                await execution
            except asyncio.CancelledError:
                pass
    except Exception as exc:
        jobs[job_id].status = "failed"
        jobs[job_id].message = str(exc)
        logger.exception("Managed crawl failed")
    finally:
        try:
            await scope.drain()
            job = jobs[job_id]
            status = (
                "cancelled" if store.get(job_id)["cancel_requested"] else job.status
            )
            if status not in {"completed", "failed", "cancelled"}:
                status = "failed"
            store.seal(
                job_id,
                status=status,
                finished_at=now(),
                completed_at=now(),
                message=job.message,
                pages_crawled=job.pages_crawled,
                output_directory=str(scope.root),
            )
        except Exception:
            logger.exception("Drainage unconfirmed; refusing sealed receipt")
            store.update(
                job_id,
                status="unknown",
                message="Drainage unconfirmed; reconciliation required",
            )
        finally:
            current_scope.reset(token)
            _executions.pop(job_id, None)
            _scopes.pop(job_id, None)
            tasks.pop(job_id, None)


class JobNotFoundError(Exception):
    """Raised when an operation targets an unknown job."""


class JobNotRunningError(Exception):
    """Raised when an operation requires an active job task."""


async def run_crawl_job(job_id: str, config: CrawlConfig):
    """
    Background task to run crawl job.

    Integrates the service layer components:
    - JobState: Persistent state tracking
    - StorageManager: File I/O operations
    """
    scope = current_scope.get()
    base_path = (
        str(scope.root.parent)
        if scope
        else os.getenv("DATA_PATH", "/var/www/html/shared")
    )

    logger.info("=" * 60)
    logger.info(f"[Job {job_id}] Starting crawl job")
    logger.info(f"[Job {job_id}] Target URL: {config.url}")
    logger.info(f"[Job {job_id}] Max Pages: {config.max_pages}")
    logger.info("=" * 60)

    job_state = JobState(job_id, base_path=base_path)
    pause_event = pause_events.setdefault(job_id, asyncio.Event())
    pause_event.set()
    storage_manager = StorageManager(job_id, base_path=base_path)

    async def _sync_job_progress(poll_interval: float = 1.0):
        while True:
            snapshot = await job_state.get_snapshot()
            if job_id in jobs:
                jobs[job_id].pages_crawled = snapshot.completed_urls
                jobs[job_id].total_pages = config.max_pages
                jobs[job_id].output_directory = (
                    snapshot.output_directory or jobs[job_id].output_directory
                )
                store = _stores.get(
                    str(Path(os.getenv("DATA_PATH", "/var/www/html/shared")).resolve())
                )
                if store and store.get(job_id):
                    store.update(job_id, pages_crawled=snapshot.completed_urls)
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

        logger.info(f"[Job {job_id}] State setup complete. Starting crawler...")

        jobs[job_id].status = "running"
        jobs[job_id].message = "Crawling in progress..."

        # Create crawler with service layer integration
        logger.info(f"[{job_id}] Creating CrawlerService...")
        crawler = CrawlerService(
            config,
            job_id=job_id,
            job_state=job_state,
            storage_manager=storage_manager,
            pause_event=pause_event,
        )

        logger.info(f"[{job_id}] CrawlerService created. Starting crawl...")
        result = await crawler.crawl()
        final_snapshot = await job_state.get_snapshot()
        result_status = result.get("status") if isinstance(result, dict) else None
        result_message = result.get("message") if isinstance(result, dict) else None
        all_urls_failed = (
            final_snapshot.completed_urls == 0 and final_snapshot.failed_urls > 0
        )

        if result_status == "failed" or all_urls_failed:
            message = (
                result_message
                or f"Crawl finished with 0 completed URLs and {final_snapshot.failed_urls} failed URL(s)."
            )
            logger.warning(
                "[%s] Crawl finished without successful pages: %s", job_id, message
            )
            jobs[job_id].status = "failed"
            jobs[job_id].message = message
            if final_snapshot.status != "failed":
                await job_state.set_error(message)
        else:
            logger.info(f"[{job_id}] Crawl completed successfully!")
            jobs[job_id].status = "completed"
            jobs[job_id].message = "Crawl completed successfully"

        jobs[job_id].pages_crawled = final_snapshot.completed_urls
        jobs[job_id].total_pages = config.max_pages
        jobs[job_id].output_directory = (
            result.get("output_directory") if isinstance(result, dict) else None
        )
        jobs[job_id].completed_at = datetime.now()

    except asyncio.CancelledError:
        jobs[job_id].status = "cancelled"
        jobs[job_id].message = "Crawl cancelled"
        jobs[job_id].completed_at = datetime.now()
        await job_state.set_status("cancelled")
        # Propagate cancellation after cleanup
        raise
    except Exception as e:
        logger.exception(
            "run_crawl_job failed", extra={"job_id": job_id, "error": str(e)}
        )
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
        pause_events.pop(job_id, None)
        job_states.pop(job_id, None)


def submit_crawl_job(config: CrawlConfig) -> CrawlResponse:
    store = runtime_store()
    # Persistent crawl output is always confined to this job's root.
    if config.sitemap_output and not Path(
        config.sitemap_output
    ).resolve().is_relative_to(store.artifact_root(config)):
        raise ValueError("sitemap_output must be inside this job's artifact root")
    try:
        limit = int(os.getenv("MAX_CONCURRENT_TASKS", "5"))
    except ValueError as exc:
        raise RuntimeError("MAX_CONCURRENT_TASKS must be a positive integer") from exc
    if limit < 1:
        raise RuntimeError("MAX_CONCURRENT_TASKS must be positive")
    record, created = store.admit(config, limit)
    if created:
        jobs[config.job_id] = CrawlStatus(
            job_id=config.job_id,
            status="pending",
            message=record["message"],
            total_pages=config.max_pages,
            started_at=datetime.now(),
        )
        install_task_tracking(asyncio.get_running_loop())
        tasks[config.job_id] = asyncio.create_task(_run_managed(config, store))
    return CrawlResponse(
        job_id=config.job_id,
        event="job_submitted" if created else "job_exists",
        data={
            "status": record["status"],
            "sealed": record["sealed"],
            "message": record["message"],
        },
        timestamp=now(),
    )


def get_job_status(job_id: str):
    return runtime_store().get(job_id)


def list_jobs() -> Dict:
    records = [
        record for record in runtime_store().records() if not record.get("retired_at")
    ]
    return {"total_jobs": len(records), "jobs": {r["job_id"]: r for r in records}}


def delete_job(job_id: str) -> bool:
    record = runtime_store().get(job_id)
    if record is None:
        return False
    if not record["sealed"]:
        raise JobNotRunningError("Cannot delete an active or unconfirmed job")
    # Retain the durable receipt/tombstone and artifacts: HAWKI-RAG owns retirement.
    runtime_store().retire(job_id)
    jobs.pop(job_id, None)
    return True


def _get_running_task(job_id: str) -> asyncio.Task:
    record = get_job_status(job_id)
    if not record:
        raise JobNotFoundError(job_id)
    if record["sealed"] or record["cancel_requested"] or record["status"] == "unknown":
        raise JobNotRunningError(job_id)
    task = tasks.get(job_id)
    if not task or task.done():
        raise JobNotRunningError(job_id)
    return task


async def cancel_job(job_id: str) -> Dict[str, object]:
    store = runtime_store()
    record = store.get(job_id)
    if not record:
        raise JobNotFoundError(job_id)
    if record["sealed"]:
        return record
    if record["status"] == "unknown":
        return store.update(job_id, cancel_requested=True)
    first_request = not record["cancel_requested"]
    store.update(job_id, cancel_requested=True, status="cancelling")
    scope = _scopes.get(job_id)
    if scope:
        scope.stopping = True
    execution = _executions.get(job_id)
    if first_request and execution and not execution.done():
        execution.cancel()
    supervisor = tasks.get(job_id)
    if supervisor:
        # A bounded response may be pending; the supervised drain continues.
        try:
            await asyncio.wait_for(asyncio.shield(supervisor), timeout=1.0)
        except asyncio.TimeoutError:
            pass
    return store.get(job_id)


async def pause_job(job_id: str) -> Dict[str, object]:
    _get_running_task(job_id)

    event = pause_events.setdefault(job_id, asyncio.Event())
    event.clear()
    runtime_store().update(job_id, status="paused")
    jobs[job_id].status = "paused"
    jobs[job_id].message = "Crawl paused"

    state = job_states.get(job_id)
    if state:
        await state.set_status("paused")

    return {"success": True, "message": f"Pause requested for job {job_id}"}


async def resume_job(job_id: str) -> Dict[str, object]:
    _get_running_task(job_id)

    event = pause_events.setdefault(job_id, asyncio.Event())
    event.set()
    runtime_store().update(job_id, status="running")
    jobs[job_id].status = "running"
    jobs[job_id].message = "Crawling in progress..."

    state = job_states.get(job_id)
    if state:
        await state.set_status("running")

    return {"success": True, "message": f"Resume requested for job {job_id}"}


async def cancel_active_crawl_tasks() -> None:
    """Keep runtime ownership until every supervised drain has actually finished."""
    active = list(tasks.items())
    for job_id, task in active:
        if job_id in _executions or any(
            store.get(job_id) for store in _stores.values()
        ):
            await cancel_job(job_id)
        elif not task.done():
            # Unregistered work cannot receive a durable seal.
            job = jobs.get(job_id)
            if job:
                job.status = "cancelled"
                job.message = "Crawl cancelled during service shutdown"
            task.cancel()
    await asyncio.gather(*(task for _, task in active), return_exceptions=True)
    for job_id, _ in active:
        tasks.pop(job_id, None)
        pause_events.pop(job_id, None)

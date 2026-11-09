from pathlib import Path as FilePath
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import FileResponse

from hawki_crawler.app import job_lifecycle
from hawki_crawler.crawler.storage.storage_manager import StorageManager

router = APIRouter()
JobId = Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,190}$")]


def job_storage(job_id):
    record = job_lifecycle.get_job_status(job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    return StorageManager(job_id, base_path=str(FilePath(record["output_directory"]).parent))


@router.get("/status/{job_id}")
async def get_status(job_id: JobId):
    """
    Get the status of a crawl job.
    """
    job = job_lifecycle.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return job


@router.get("/jobs")
async def list_jobs():
    """
    List all crawl jobs.
    """
    return job_lifecycle.list_jobs()


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: JobId):
    """
    Delete a job from the jobs list.
    """
    try:
        if not job_lifecycle.delete_job(job_id):
            raise HTTPException(status_code=404, detail="Job not found")
    except job_lifecycle.JobNotRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"message": f"Job {job_id} retired from listing; artifacts and sealed receipt retained"}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: JobId):
    """
    Cancel a running crawl job.
    """
    try:
        return await job_lifecycle.cancel_job(job_id)
    except job_lifecycle.JobNotFoundError:
        raise HTTPException(status_code=404, detail="Job not found")
    except job_lifecycle.JobNotRunningError:
        raise HTTPException(status_code=400, detail="Job is not running or already finished")


@router.post("/jobs/{job_id}/pause")
async def pause_job(job_id: JobId):
    """
    Pause a running crawl job after the current URL/batch finishes.
    """
    try:
        return await job_lifecycle.pause_job(job_id)
    except job_lifecycle.JobNotFoundError:
        raise HTTPException(status_code=404, detail="Job not found")
    except job_lifecycle.JobNotRunningError:
        raise HTTPException(status_code=400, detail="Job is not running or already finished")


@router.post("/jobs/{job_id}/resume")
async def resume_job(job_id: JobId):
    """
    Resume a paused crawl job from its current in-memory URL queue.
    """
    try:
        return await job_lifecycle.resume_job(job_id)
    except job_lifecycle.JobNotFoundError:
        raise HTTPException(status_code=404, detail="Job not found")
    except job_lifecycle.JobNotRunningError:
        raise HTTPException(status_code=400, detail="Job is not running or already finished")


@router.get("/jobs/{job_id}/files")
async def list_job_files(job_id: JobId):
    """
    List all files for a specific job.
    """
    storage_manager = job_storage(job_id)

    if not storage_manager.get_job_directory().exists():
        raise HTTPException(status_code=404, detail="Job not found or no data available")

    files = storage_manager.list_files(relative=True)

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


@router.get("/jobs/{job_id}/files/{file_path:path}")
async def download_job_file(job_id: JobId, file_path: str):
    """
    Download a specific file from a job's directory.
    """
    storage_manager = job_storage(job_id)

    absolute_path = storage_manager.get_file_path(file_path)

    if not absolute_path:
        raise HTTPException(status_code=404, detail="File not found")

    file_info = storage_manager.get_file_info(file_path)
    media_type = file_info['type'] if file_info else 'application/octet-stream'

    return FileResponse(
        path=str(absolute_path),
        media_type=media_type,
        filename=absolute_path.name
    )

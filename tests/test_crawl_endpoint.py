import asyncio
import logging
import uuid

import pytest
import pytest_asyncio
import httpx
from hamcrest import assert_that, greater_than, has_entries, has_item, instance_of, has_length

from hawki_crawler.app.main import app

logger = logging.getLogger(__name__)




@pytest.fixture
def data_path(tmp_path, monkeypatch):
    """The main storage of the FastApi via DATA_PATH env."""
    monkeypatch.setenv("DATA_PATH", str(tmp_path))
    return tmp_path


@pytest_asyncio.fixture
async def client():
    """A client to send requests to FastApi app."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def wait_for_status(client):
    """Function fixture to wait for a finished, failed or aborted job status."""
    TERMINAL_STATUSES = ("completed", "failed", "cancelled")
    async def _wait(job_id, interval=2, attempts=15):
        for i in range(attempts):
            await asyncio.sleep(interval)
            response = await client.get(f"/status/{job_id}")
            body = response.json()
            status = body["status"]
            logger.info(
                "Job %s status=%s pages=%s msg=%s",
                job_id,
                status,
                body.get("pages_crawled"),
                body.get("message"),
            )
            if status in TERMINAL_STATUSES:
                return body
        raise TimeoutError(f"Job {job_id} did not finish within {attempts * interval}s, last status: {status}")

    return _wait


@pytest.fixture
def list_files(client):
    async def _list(job_id):
        response = await client.get(f"/jobs/{job_id}/files")
        response.raise_for_status()
        return response.json()

    return _list


@pytest.fixture
def download_file(client):
    async def _download(job_id, path):
        response = await client.get(f"/jobs/{job_id}/files/{path}")
        response.raise_for_status()
        return response

    return _download


@pytest.mark.asyncio
async def test_crawl_endpoint(client, data_path, wait_for_status, list_files, download_file):
    """Test that first site on sitemap can be crawled.
    
    Warning: test will need changes if page content changes.
    """
    job_id = str(uuid.uuid4())
    config = {
        "job_id": job_id,
        "url": "https://www.hawk.de/sitemaps/main/sitemap.xml",
        "max_pages": 1,
        "skip_images": True,
        "max_concurrency": 1,
        "max_rpm": 30,
    }

    response = await client.post("/crawl", json=config)
    result = response.json()
    assert result["data"]["status"] == "pending"

    final = await wait_for_status(job_id)

    assert_that(final, has_entries(
        job_id=job_id,
        status="completed",
        message="Crawl completed successfully",
        pages_crawled=1,
        total_pages=1,
        output_directory=f"{data_path}/{job_id}",
        started_at=instance_of(str),
        completed_at=instance_of(str),
    ))

    files_result = await list_files(job_id)

    a_file_entry = has_entries(
        name=instance_of(str),
        path=instance_of(str),
        size=greater_than(0),
        modified=instance_of(float),
        type=instance_of(str),
    )

    assert_that(files_result, has_entries(
        job_id=job_id,
        total_files=greater_than(0),
        files=instance_of(list),
    ))

    for f in files_result["files"]:
        assert_that(f, a_file_entry)

    for name in ("completed_urls.json", "crawler.log", "job_state.json",
                 "summary.json", "urls_index.json", "content.md", "data.json"):
        assert_that(files_result["files"], has_item(has_entries(name=name)))

    assert_that(files_result["files"], has_item(has_entries(
        name="urls_chunk_0000.json", type="application/json",
    )))

    dl_completed = await download_file(job_id, "completed_urls.json")
    assert dl_completed.status_code == 200
    completed_urls = dl_completed.json()

    assert_that(completed_urls, has_entries(
        job_id=job_id,
        total_completed=1,
        generated_at=instance_of(str),
        records=instance_of(list),
    ))

    assert_that( completed_urls["records"], has_length(1))
    record = completed_urls["records"][0]
    assert_that(record, has_entries(
        url="https://www.hawk.de/de/hochschule/fakultaeten/ressourcenmanagement",
        source_url="https://www.hawk.de/de/hochschule/fakultaeten/ressourcenmanagement",
        canonical_url="https://www.hawk.de/de/hochschule/fakultaeten/ressourcenmanagement",
        http_status=200,
        source_type="sitemap",
        depth=0,
        images_count=0,
        pdf_count=0,
        file_count=0,
    ))
    assert record["content_status"] in {"success", "noisy"}

    content_md_path = next(f["path"] for f in files_result["files"] if f["name"] == "content.md")
    md_content = await download_file(job_id, content_md_path)
    assert md_content.status_code == 200

    assert_that(md_content.text,
        "> Bei uns stehen die nachhaltige Zukunft von Natur und Gesellschaft im Mittelpunkt."
    )

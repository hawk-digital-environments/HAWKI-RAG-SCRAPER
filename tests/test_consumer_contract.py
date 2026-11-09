"""Optional tests against the actual RAWKI clients, imported strictly read-only.

These exercise HTTP/runtime compatibility, not a Temporal/indexer smoke test.
"""

import asyncio
import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import uvicorn

from hawki_crawler.app import job_lifecycle
from hawki_crawler.app.main import app
from hawki_crawler.crawler.models import CrawlConfig

RAWKI = Path("/Users/ixdlab/Projects/HAWKI/RAWKI")


def consumer_imports(monkeypatch):
    if not RAWKI.is_dir():
        pytest.skip("Read-only RAWKI checkout is not available")
    pytest.importorskip(
        "sqlalchemy", reason="Consumer contract test requires test-only SQLAlchemy"
    )
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    for relative in (
        "python_backend/src",
        "python_rag/packages/contracts/src",
        "python_rag/packages/external_jobs/src",
    ):
        monkeypatch.syspath_prepend(str(RAWKI / relative))
    from hawki_backend.url_ingestion.errors import UrlIngestionError
    from hawki_backend.url_ingestion.quiescence import ExternalJobQuiescence
    from hawki_external_jobs import ExternalJobClient

    return ExternalJobClient, ExternalJobQuiescence, UrlIngestionError


@asynccontextmanager
async def crawler_server():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, log_config=None, lifespan="off", loop="asyncio")
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(100):
            if server.started:
                break
            if task.done():
                await task
            await asyncio.sleep(0.01)
        assert server.started
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        sock.close()


class ReceiptRepository:
    """Only persistence is replaced; the consumer's HTTP/receipt logic is real."""

    def __init__(self, job_id):
        self.state = {"job_id": job_id, "quiescent": False}

    def generation(self, operation_id):
        return {"external_job": self.state}

    def record_external_job(self, operation_id, values):
        self.state.update(values)


@pytest.mark.asyncio
async def test_actual_hawki_client_consumes_start_and_terminal_receipt(monkeypatch):
    ExternalJobClient, ExternalJobQuiescence, _ = consumer_imports(monkeypatch)
    async with crawler_server() as base:
        client = ExternalJobClient(
            base_url=base,
            start_path="/crawl",
            status_path="/status/{job_id}",
            poll_interval_seconds=0.5,
            poll_timeout_seconds=5,
        )
        try:
            # Current consuming scraper payload shape. Browser is honestly failed closed.
            response = await asyncio.to_thread(
                client.start_and_wait,
                dict(
                    job_id="consumer-shaped",
                    source_id="source-11",
                    source_url="https://example.com/",
                    url="https://example.com/",
                    output_dir="sources/source-11/raw/",
                    max_pages=1,
                ),
            )
            assert response["external_job_id"] == "consumer-shaped"
            assert response["status"] == "failed"
            assert response["output_directory"].endswith(
                "/sources/source-11/raw/consumer-shaped"
            )
            assert (
                response["sealed"]
                and response["quiescent"]
                and response["writer_admission_closed"]
            )
            repository = ReceiptRepository("consumer-shaped")
            boundary = ExternalJobQuiescence(repository)
            await asyncio.to_thread(
                boundary.ensure,
                {
                    "url_ingestion_operation_id": "op-11",
                    "workflow_input": {"external_services": {"scraper_url": base}},
                },
            )
            assert repository.state["quiescent"]
            assert repository.state["writer_admission_closed"]
        finally:
            client.session.close()


@pytest.mark.asyncio
async def test_actual_hawki_quiescence_client_cancels_then_accepts_sealed_receipt(
    monkeypatch,
):
    _, ExternalJobQuiescence, UrlIngestionError = consumer_imports(monkeypatch)
    ready = asyncio.Event()

    async def controlled_executor(job_id, config):
        ready.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(job_lifecycle, "run_crawl_job", controlled_executor)
    job_lifecycle.submit_crawl_job(
        CrawlConfig(job_id="consumer-cancel", url="https://example.com/")
    )
    await ready.wait()
    repository = ReceiptRepository("consumer-cancel")
    boundary = ExternalJobQuiescence(repository)
    async with crawler_server() as base:
        generation = {
            "url_ingestion_operation_id": "op-11",
            "workflow_input": {"external_services": {"scraper_url": base}},
        }
        with pytest.raises(UrlIngestionError) as result:
            await asyncio.to_thread(boundary.ensure, generation)
        assert result.value.status == 202
        await asyncio.to_thread(boundary.ensure, generation)
        assert repository.state["lifecycle"] == "cancelled"
        assert (
            repository.state["quiescent"]
            and repository.state["writer_admission_closed"]
        )

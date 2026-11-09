"""Lifecycle contract tests use controlled executors; no fake browser smoke claim."""

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from hawki_crawler.app import job_lifecycle as lifecycle
from hawki_crawler.app.main import app
from hawki_crawler.crawler.models import CrawlConfig
from hawki_crawler.crawler.state.job_state import JobState
from hawki_crawler.crawler.state.progress_tracker import ProgressTracker
from hawki_crawler.crawler.storage.storage_manager import StorageManager
from hawki_crawler.runtime.scope import JobScope, current_scope
from hawki_crawler.runtime.store import RuntimeStore
from hawki_crawler.runtime.writes import AdmissionClosed, AsyncFile, mkdir, open_sync


@pytest_asyncio.fixture
async def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_PATH", str(tmp_path))
    monkeypatch.setenv("MAX_CONCURRENT_TASKS", "2")
    store = lifecycle.runtime_store()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, store
    await lifecycle.cancel_active_crawl_tasks()
    lifecycle.close_runtime_stores()
    lifecycle.jobs.clear()
    lifecycle.pause_events.clear()
    lifecycle.job_states.clear()


def payload(job_id="contract-job"):
    return dict(
        job_id=job_id,
        url="https://example.com/",
        max_pages=1,
        output_dir="output",
        source_id="source-11",
        generation=11,
        url_ingestion_operation_id="operation-11",
    )


async def finish(job_id):
    task = lifecycle.tasks.get(job_id)
    if task:
        await asyncio.wait_for(asyncio.shield(task), 5)
    return lifecycle.get_job_status(job_id)


@pytest.mark.asyncio
async def test_duplicate_active_lost_response_and_capacity(runtime, monkeypatch):
    client, store = runtime
    started = []

    async def execute(job_id, config):
        started.append(job_id)
        await asyncio.Event().wait()

    monkeypatch.setattr(lifecycle, "run_crawl_job", execute)
    responses = await asyncio.gather(
        *(client.post("/crawl", json=payload()) for _ in range(8))
    )
    assert all(r.status_code == 200 for r in responses)
    await asyncio.sleep(0)
    assert started == ["contract-job"]
    assert responses[0].json()["job_id"] == "contract-job"
    assert store.get("contract-job")["metadata"]["generation"] == 11
    assert (await client.post("/crawl", json=payload("second"))).status_code == 200
    assert (await client.post("/crawl", json=payload("third"))).status_code == 429
    assert (
        await client.post("/crawl", json={**payload(), "max_pages": 2})
    ).status_code == 409
    assert (await client.delete("/jobs/contract-job")).status_code == 409
    assert (await client.post("/jobs/contract-job/cancel")).json()["sealed"] is True
    assert (await client.post("/crawl", json=payload("third"))).status_code == 200


@pytest.mark.asyncio
async def test_cancel_waits_for_child_resources_and_terminal_does_not_imply_sealed(
    runtime, monkeypatch
):
    client, store = runtime
    started, cleanup, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def child():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup.set()
            await release.wait()

    async def execute(job_id, config):
        asyncio.create_task(child())
        await asyncio.Event().wait()

    monkeypatch.setattr(lifecycle, "run_crawl_job", execute)
    await client.post("/crawl", json=payload())
    await started.wait()
    receipt = (await client.post("/jobs/contract-job/cancel")).json()
    await cleanup.wait()
    assert receipt["status"] == "cancelling"
    assert receipt["cancel_requested"] is True
    assert receipt["sealed"] is False
    assert (await client.get("/status/contract-job")).json()["quiescent"] is False
    release.set()
    receipt = await finish("contract-job")
    assert receipt["status"] == "cancelled"
    assert receipt["terminal"] and receipt["sealed"] and receipt["quiescent"]
    assert receipt["writer_admission_closed"] and receipt["sealed_at"]


@pytest.mark.asyncio
async def test_sealed_identity_restart_delete_and_late_writes(runtime, monkeypatch):
    client, store = runtime
    retained = {}

    async def execute(job_id, config):
        state = JobState(job_id, str(store.root))
        await state.initialize()
        manager = StorageManager(job_id, str(store.root))
        manager.ensure_job_directory()
        directory = manager.create_hash_directory("a" * 64, create_files_dir=True)
        await manager.save_hash_content("a" * 64, "original")
        retained.update(
            state=state,
            manager=manager,
            directory=directory,
            progress=ProgressTracker(),
        )
        lifecycle.jobs[job_id].status = "completed"

    monkeypatch.setattr(lifecycle, "run_crawl_job", execute)
    await client.post("/crawl", json=payload())
    receipt = await finish("contract-job")
    assert receipt["sealed"] is True
    root = store.root / "contract-job"
    before = {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    for action in (
        retained["manager"].save_hash_content("a" * 64, "late"),
        retained["manager"].save_hash_json("a" * 64, {"late": True}),
        retained["manager"].save_hash_image("a" * 64, "late.png", b"late"),
        retained["manager"].upsert_completed_url_record(
            {"url": "https://example.com"}, url_hash="a" * 64
        ),
        retained["state"].increment_completed(),
        retained["progress"].increment_completed(),
    ):
        with pytest.raises(AdmissionClosed):
            await action
    with pytest.raises(AdmissionClosed):
        mkdir(root / "late")
    with pytest.raises(AdmissionClosed):
        with open_sync(root / "sitemap.json", "w"):
            pass
    assert before == {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    assert (await client.post("/jobs/contract-job/resume")).status_code == 400
    assert (await client.post("/crawl", json=payload())).json()["event"] == "job_exists"
    assert "contract-job" not in lifecycle.tasks
    assert (await client.delete("/jobs/contract-job")).status_code == 200
    assert (await client.post("/crawl", json=payload())).json()["data"]["sealed"]
    # Removing artifact data externally must not erase the permanent identity.
    assert store.path("contract-job").is_file()


def test_restart_reconciliation_is_fail_closed(tmp_path):
    store = RuntimeStore(tmp_path)
    config = CrawlConfig(**payload())
    store.admit(config, 2)
    store.update(config.job_id, status="completed")
    assert (
        store.get(config.job_id)["terminal"] and not store.get(config.job_id)["sealed"]
    )
    store.admit(CrawlConfig(**payload("sealed")), 2)
    store.seal("sealed", status="cancelled")
    store.close()
    recovered = RuntimeStore(tmp_path)
    try:
        assert recovered.get(config.job_id)["status"] == "unknown"
        assert not recovered.get(config.job_id)["sealed"]
        assert recovered.get("sealed")["sealed"]
        assert recovered.admit(config, 2)[1] is False
        with pytest.raises(RuntimeError):
            RuntimeStore(tmp_path)
    finally:
        recovered.close()


@pytest.mark.asyncio
async def test_open_writer_prevents_seal(runtime):
    _, store = runtime
    store.admit(CrawlConfig(**payload()), 2)
    root = store.root / "contract-job"
    mkdir(root)
    async with AsyncFile(root / "held.txt", "w") as stream:
        await stream.write("hello")
        with pytest.raises(BlockingIOError):
            store.seal("contract-job", status="completed")
        assert not store.get("contract-job")["sealed"]
    store.seal("contract-job", status="completed")


@pytest.mark.asyncio
async def test_browser_dispatch_fails_closed_and_releases_capacity(
    runtime, monkeypatch
):
    monkeypatch.setattr(
        "hawki_crawler.runtime.browser.linux_namespaces_available", lambda: False
    )
    client, store = runtime
    await client.post("/crawl", json=payload())
    receipt = await finish("contract-job")
    assert receipt["status"] == "failed"
    assert "No browser was launched" in receipt["message"]
    assert receipt["sealed"] and receipt["writer_admission_closed"]
    assert (await client.post("/crawl", json=payload("next"))).status_code == 200


@pytest.mark.asyncio
async def test_cancel_before_task_starts_and_unknown_is_not_sealed(runtime):
    _, store = runtime
    lifecycle.submit_crawl_job(CrawlConfig(**payload()))
    receipt = await lifecycle.cancel_job("contract-job")
    assert receipt["sealed"] and receipt["status"] == "cancelled"
    store.admit(CrawlConfig(**payload("uncertain")), 2)
    store.update("uncertain", status="unknown")
    receipt = await lifecycle.cancel_job("uncertain")
    assert receipt["status"] == "unknown" and not receipt["sealed"]


@pytest.mark.asyncio
async def test_exception_closes_http_resource_and_drains_delayed_task(
    runtime, monkeypatch
):
    from hawki_crawler.runtime.network import SafeSession

    retained = {}

    async def execute(job_id, config):
        retained["session"] = SafeSession()

        async def delayed():
            await asyncio.sleep(60)

        retained["child"] = asyncio.create_task(delayed())
        raise RuntimeError("executor failure")

    monkeypatch.setattr(lifecycle, "run_crawl_job", execute)
    lifecycle.submit_crawl_job(CrawlConfig(**payload()))
    receipt = await finish("contract-job")
    assert receipt["sealed"] and receipt["status"] == "failed"
    assert retained["session"].closed and retained["child"].done()


@pytest.mark.asyncio
async def test_delayed_callbacks_and_child_start_admission_close(runtime, monkeypatch):
    _, store = runtime
    retained = {}

    async def execute(job_id, config):
        retained["scope"] = current_scope.get()
        retained["timer"] = asyncio.get_running_loop().call_later(60, lambda: None)
        lifecycle.jobs[job_id].status = "completed"

    monkeypatch.setattr(lifecycle, "run_crawl_job", execute)
    lifecycle.submit_crawl_job(CrawlConfig(**payload()))
    assert (await finish("contract-job"))["sealed"]
    assert retained["timer"].cancelled()
    token = current_scope.set(retained["scope"])
    try:
        with pytest.raises(RuntimeError, match="admission is closed"):
            asyncio.create_task(asyncio.sleep(0))
    finally:
        current_scope.reset(token)


@pytest.mark.asyncio
async def test_consumer_output_tree_is_confined_and_job_specific(runtime, monkeypatch):
    client, store = runtime

    async def execute(job_id, config):
        scope = current_scope.get()
        manager = StorageManager(job_id, str(scope.root.parent))
        manager.ensure_job_directory()
        manager.create_hash_directory("b" * 64)
        await manager.save_hash_content("b" * 64, "artifact")
        lifecycle.jobs[job_id].status = "completed"

    monkeypatch.setattr(lifecycle, "run_crawl_job", execute)
    request = {**payload(), "output_dir": "/shared/sources/source-11/raw/"}
    assert (await client.post("/crawl", json=request)).status_code == 200
    receipt = await finish("contract-job")
    assert receipt["output_directory"] == str(
        store.root / "sources/source-11/raw/contract-job"
    )
    listing = (await client.get("/jobs/contract-job/files")).json()
    content = next(f["path"] for f in listing["files"] if f["name"] == "content.md")
    assert (await client.get("/jobs/contract-job/files/" + content)).text == "artifact"
    with pytest.raises(AdmissionClosed):
        async with AsyncFile(Path(receipt["output_directory"]) / "late", "w"):
            pass
    assert (
        await client.post(
            "/crawl",
            json={**payload("next"), "output_dir": "/shared/sources/source-11/raw/"},
        )
    ).status_code == 200
    await finish("next")
    assert (
        await client.post(
            "/crawl",
            json={**payload("nested"), "output_dir": receipt["output_directory"]},
        )
    ).status_code == 409
    assert (
        await client.post(
            "/crawl", json={**payload("escape"), "output_dir": "/tmp/unmanaged"}
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_dns_work_drains_before_sealed_receipt(runtime, monkeypatch):
    import socket
    import threading

    from hawki_crawler.runtime import network

    client, store = runtime
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    retained = {}

    def resolve(host, port, **kwargs):
        loop.call_soon_threadsafe(started.set)
        release.wait(5)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)

    async def execute(job_id, config):
        async with network.SafeSession() as session:
            retained["session"] = session
            async with session.get("https://public.example/"):
                pass

    monkeypatch.setattr(lifecycle, "run_crawl_job", execute)
    await client.post("/crawl", json=payload())
    await started.wait()
    try:
        receipt = (await client.post("/jobs/contract-job/cancel")).json()
        assert not receipt["sealed"]
        assert not retained["session"].closed
    finally:
        release.set()
    assert (await finish("contract-job"))["sealed"]
    assert retained["session"].closed


@pytest.mark.asyncio
async def test_symlink_alias_cannot_bypass_sealed_fence(runtime):
    _, store = runtime
    store.admit(CrawlConfig(**payload()), 2)
    root = store.root / "contract-job"
    mkdir(root)
    store.seal("contract-job", status="completed")
    alias = store.root.parent / ("alias-" + store.root.name)
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(AdmissionClosed):
        async with AsyncFile(alias / "late", "w"):
            pass
    assert not (root / "late").exists()


def test_uvloop_tracks_delayed_work(tmp_path):
    uvloop = pytest.importorskip("uvloop")
    from hawki_crawler.runtime.scope import install_task_tracking

    loop = uvloop.new_event_loop()

    async def check():
        install_task_tracking(loop)
        scope = JobScope(tmp_path)
        token = current_scope.set(scope)
        try:
            handle = loop.call_later(60, lambda: None)
            await scope.drain()
            assert handle.cancelled()
        finally:
            current_scope.reset(token)

    try:
        loop.run_until_complete(check())
    finally:
        loop.close()

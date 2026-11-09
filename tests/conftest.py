import os
import sys
from pathlib import Path

import pytest_asyncio

ROOT_DIR = Path(__file__).resolve().parents[1]

os.environ.setdefault("CRAWL4_AI_BASE_DIRECTORY", "/tmp/customcrawler-crawl4ai")

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


@pytest_asyncio.fixture(autouse=True)
async def isolated_runtime(tmp_path, monkeypatch):
    """Tests never initialize the production DATA_PATH or retain runtime owners."""
    from hawki_crawler.app import job_lifecycle
    monkeypatch.setenv("DATA_PATH", str(tmp_path))
    yield
    await job_lifecycle.cancel_active_crawl_tasks()
    job_lifecycle.close_runtime_stores()

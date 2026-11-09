import json
from pathlib import Path
from typing import Any, Dict

from hawki_crawler.crawler.storage.page_output import (
    CONTENT_FILENAME,
    METADATA_FILENAME,
    PAGE_ROOT_DIRNAME,
)
from hawki_crawler.runtime.writes import AsyncFile
from hawki_crawler.runtime.writes import mkdir as guarded_mkdir


class PageStore:
    """Creates page directories and stores page metadata/content files."""

    def __init__(self, *, job_dir: Path) -> None:
        self.job_dir = job_dir

    def get_hash_directory(self, url_hash: str) -> Path:
        if len(url_hash) < 4:
            return self.job_dir / url_hash

        return self.job_dir / PAGE_ROOT_DIRNAME / url_hash[0] / url_hash[1] / url_hash[2] / url_hash[3] / url_hash

    def get_page_directory(self, page_number: int) -> Path:
        return self.job_dir / PAGE_ROOT_DIRNAME / f"page_{page_number:05d}"

    def create_hash_directory(
        self,
        url_hash: str,
        create_images_dir: bool = True,
        create_files_dir: bool = False,
    ) -> Path:
        hash_dir = self.get_hash_directory(url_hash)
        guarded_mkdir(hash_dir, parents=True, exist_ok=True)

        if create_images_dir:
            images_dir = hash_dir / "images"
            guarded_mkdir(images_dir, exist_ok=True)

        if create_files_dir:
            files_dir = hash_dir / "files"
            guarded_mkdir(files_dir, exist_ok=True)

        return hash_dir

    def create_page_directory(
        self,
        page_number: int,
        create_images_dir: bool = True,
        create_files_dir: bool = False,
    ) -> Path:
        page_dir = self.get_page_directory(page_number)
        guarded_mkdir(page_dir, parents=True, exist_ok=True)

        if create_images_dir:
            images_dir = page_dir / "images"
            guarded_mkdir(images_dir, exist_ok=True)

        if create_files_dir:
            files_dir = page_dir / "files"
            guarded_mkdir(files_dir, exist_ok=True)

        return page_dir

    async def save_hash_json(self, url_hash: str, data: Dict[str, Any]) -> None:
        json_file = self.get_hash_directory(url_hash) / METADATA_FILENAME

        async with AsyncFile(json_file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False))

    async def save_hash_content(self, url_hash: str, content: str) -> None:
        content_file = self.get_hash_directory(url_hash) / CONTENT_FILENAME

        async with AsyncFile(content_file, "w", encoding="utf-8") as f:
            await f.write(content if content else "")

    async def save_page_json(self, page_number: int, data: Dict[str, Any]) -> None:
        json_file = self.get_page_directory(page_number) / METADATA_FILENAME

        async with AsyncFile(json_file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False))

    async def save_page_content(self, page_number: int, content: str) -> None:
        content_file = self.get_page_directory(page_number) / CONTENT_FILENAME

        async with AsyncFile(content_file, "w", encoding="utf-8") as f:
            await f.write(content if content else "")

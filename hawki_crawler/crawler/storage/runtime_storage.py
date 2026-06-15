"""Runtime storage service for crawler output directories."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from hawki_crawler.crawler.storage.runtime_directories import (
    create_runtime_page_directory,
    setup_output_directory,
)


class RuntimeStorageService:
    """Create crawl output directories using managed or legacy storage paths."""

    def __init__(
        self,
        *,
        storage_manager: Optional[Any],
        output_dir: Path,
        skip_images: bool,
    ) -> None:
        self.storage_manager = storage_manager
        self.output_dir = output_dir
        self.skip_images = skip_images

    async def setup_directories(self) -> None:
        await setup_output_directory(
            storage_manager=self.storage_manager,
            output_dir=self.output_dir,
        )

    async def create_page_directory(
        self,
        page_number: int,
        create_files_dir: bool = False,
    ) -> Path:
        return await create_runtime_page_directory(
            storage_manager=self.storage_manager,
            output_dir=self.output_dir,
            page_number=page_number,
            skip_images=self.skip_images,
            create_files_dir=create_files_dir,
        )

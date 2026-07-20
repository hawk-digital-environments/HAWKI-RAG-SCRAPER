"""Runtime directory helpers for crawler output."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


async def setup_output_directory(
    *,
    storage_manager: Optional[Any],
    output_dir: Path,
) -> None:
    """Create the job output directory using storage-manager or legacy paths."""
    if storage_manager:
        storage_manager.ensure_job_directory()
    else:
        output_dir.mkdir(parents=True, exist_ok=True)


async def create_runtime_page_directory(
    *,
    storage_manager: Optional[Any],
    output_dir: Path,
    page_number: int,
    skip_images: bool,
    create_files_dir: bool = False,
) -> Path:
    """Create a page directory using storage-manager or legacy page folders."""
    if storage_manager:
        return storage_manager.create_page_directory(
            page_number,
            create_images_dir=not skip_images,
            create_files_dir=create_files_dir,
        )

    page_dir = output_dir / f"page_{page_number:05d}"
    page_dir.mkdir(exist_ok=True)

    if not skip_images:
        images_dir = page_dir / "images"
        images_dir.mkdir(exist_ok=True)

    if create_files_dir:
        files_dir = page_dir / "files"
        files_dir.mkdir(exist_ok=True)

    return page_dir

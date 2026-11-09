import json
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict

from hawki_crawler.crawler.storage.page_output import DIAGNOSTICS_DIRNAME
from hawki_crawler.runtime.writes import AsyncFile
from hawki_crawler.runtime.writes import mkdir as guarded_mkdir


class PageDataStore:
    """Persist extracted page metadata, markdown content, and diagnostics."""

    def __init__(
        self,
        *,
        storage_manager: Any,
        create_page_directory: Callable[..., Awaitable[Path]],
        skip_images: bool,
    ) -> None:
        self.storage_manager = storage_manager
        self.create_page_directory = create_page_directory
        self.skip_images = skip_images

    async def save_page_data(
        self,
        page_data: Dict,
        page_number: int,
        url_hash: str,
    ) -> None:
        low_quality_content = page_data.get("low_quality_content")
        raw_html = page_data.get("html_content")
        should_save_raw = bool(raw_html) and (low_quality_content or not page_data.get("markdown"))

        if self.storage_manager:
            await self._save_hash_page_data(
                page_data,
                url_hash=url_hash,
                low_quality_content=low_quality_content,
                raw_html=raw_html,
                should_save_raw=should_save_raw,
            )
            return

        await self._save_legacy_page_data(
            page_data,
            page_number=page_number,
            low_quality_content=low_quality_content,
            raw_html=raw_html,
            should_save_raw=should_save_raw,
        )

    async def _save_hash_page_data(
        self,
        page_data: Dict,
        *,
        url_hash: str,
        low_quality_content: str | None,
        raw_html: str | None,
        should_save_raw: bool,
    ) -> None:
        self.storage_manager.create_hash_directory(url_hash, create_images_dir=not self.skip_images)
        await self.storage_manager.save_hash_json(url_hash, page_data["data"])
        await self.storage_manager.save_hash_content(url_hash, page_data["markdown"] if page_data["markdown"] else "")
        await self.storage_manager.upsert_completed_url_record(page_data["data"], url_hash=url_hash)

        if low_quality_content:
            diagnostics_dir = self.storage_manager.get_hash_directory(url_hash) / DIAGNOSTICS_DIRNAME
            await self._write_diagnostic(diagnostics_dir, "low_q.txt", low_quality_content)
        if should_save_raw:
            diagnostics_dir = self.storage_manager.get_hash_directory(url_hash) / DIAGNOSTICS_DIRNAME
            await self._write_diagnostic(diagnostics_dir, "raw.html", raw_html or "")

    async def _save_legacy_page_data(
        self,
        page_data: Dict,
        *,
        page_number: int,
        low_quality_content: str | None,
        raw_html: str | None,
        should_save_raw: bool,
    ) -> None:
        page_dir = await self.create_page_directory(page_number)
        json_filename = page_dir / "data.json"
        async with AsyncFile(json_filename, "w", encoding="utf-8") as f:
            await f.write(json.dumps(page_data["data"], indent=2, ensure_ascii=False, allow_nan=False))

        md_filename = page_dir / "content.md"
        async with AsyncFile(md_filename, "w", encoding="utf-8") as f:
            await f.write(page_data["markdown"] if page_data["markdown"] else "")

        if low_quality_content:
            diagnostics_dir = page_dir / DIAGNOSTICS_DIRNAME
            await self._write_diagnostic(diagnostics_dir, "low_q.txt", low_quality_content)
        if should_save_raw:
            diagnostics_dir = page_dir / DIAGNOSTICS_DIRNAME
            await self._write_diagnostic(diagnostics_dir, "raw.html", raw_html or "")

    @staticmethod
    async def _write_diagnostic(diagnostics_dir: Path, filename: str, content: str) -> None:
        guarded_mkdir(diagnostics_dir, exist_ok=True)
        diagnostic_file = diagnostics_dir / filename
        async with AsyncFile(diagnostic_file, "w", encoding="utf-8") as f:
            await f.write(content)

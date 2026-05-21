import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import aiofiles

from hawki_crawler.crawler.storage.page_output import CONTENT_FILENAME, METADATA_FILENAME


class CompletedUrlManifestStore:
    """Maintains the job-level manifest of successfully saved crawl pages."""

    def __init__(
        self,
        *,
        job_id: str,
        job_dir: Path,
        get_hash_directory: Callable[[str], Path],
        get_page_directory: Callable[[int], Path],
    ) -> None:
        self.job_id = job_id
        self.job_dir = job_dir
        self._get_hash_directory = get_hash_directory
        self._get_page_directory = get_page_directory
        self._lock = asyncio.Lock()

    def get_path(self) -> Path:
        return self.job_dir / "completed_urls.json"

    async def upsert_record(
        self,
        metadata: Dict[str, Any],
        *,
        url_hash: Optional[str] = None,
        page_number: Optional[int] = None,
    ) -> None:
        if not metadata:
            return

        record_url = metadata.get("url")
        if not record_url:
            return

        page_dir = self._resolve_page_directory(
            metadata,
            url_hash=url_hash,
            page_number=page_number,
        )
        if page_dir is None:
            return

        record = self._build_record(
            metadata,
            record_url=record_url,
            page_dir=page_dir,
            url_hash=url_hash,
        )

        async with self._lock:
            manifest = await self._load_manifest()
            records = manifest.get("records")
            if not isinstance(records, list):
                records = []

            replaced = False
            for index, existing in enumerate(records):
                if isinstance(existing, dict) and existing.get("url") == record_url:
                    records[index] = record
                    replaced = True
                    break
            if not replaced:
                records.append(record)

            records.sort(key=lambda item: ((item or {}).get("fetched_at") or "", (item or {}).get("url") or ""))
            manifest["generated_at"] = datetime.utcnow().isoformat() + "Z"
            manifest["total_completed"] = len(records)
            manifest["records"] = records

            async with aiofiles.open(self.get_path(), "w", encoding="utf-8") as f:
                await f.write(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False))

    def _resolve_page_directory(
        self,
        metadata: Dict[str, Any],
        *,
        url_hash: Optional[str],
        page_number: Optional[int],
    ) -> Optional[Path]:
        if url_hash:
            return self._get_hash_directory(url_hash)
        if page_number is not None:
            return self._get_page_directory(page_number)

        metadata_hashes = metadata.get("hashes") or {}
        derived_hash = metadata_hashes.get("url_sha256")
        if derived_hash:
            return self._get_hash_directory(str(derived_hash))
        return None

    def _build_record(
        self,
        metadata: Dict[str, Any],
        *,
        record_url: str,
        page_dir: Path,
        url_hash: Optional[str],
    ) -> Dict[str, Any]:
        try:
            page_dir_relative = str(page_dir.relative_to(self.job_dir))
        except Exception:
            page_dir_relative = str(page_dir)

        files_info = metadata.get("files") or {}
        timestamps = metadata.get("timestamps") or {}
        status = metadata.get("status") or {}
        hashes = metadata.get("hashes") or {}
        source = metadata.get("source") or {}
        quality = metadata.get("quality") or {}
        documents = metadata.get("documents") or {}

        content_filename = files_info.get("content_markdown", CONTENT_FILENAME)
        metadata_filename = files_info.get("metadata_json", METADATA_FILENAME)

        return {
            "page_id": metadata.get("page_id") or hashes.get("url_sha256"),
            "url": record_url,
            "source_url": metadata.get("source_url"),
            "canonical_url": metadata.get("canonical_url"),
            "url_hash": hashes.get("url_sha256") or url_hash,
            "content_hash": hashes.get("content_sha256"),
            "title": metadata.get("title"),
            "lang": metadata.get("lang"),
            "fetched_at": timestamps.get("fetched_at"),
            "published_at": timestamps.get("published_at"),
            "updated_at": timestamps.get("updated_at"),
            "http_status": status.get("http_status"),
            "content_status": status.get("content_status"),
            "word_count": status.get("word_count"),
            "source_type": source.get("type"),
            "depth": source.get("depth"),
            "quality_score": quality.get("score"),
            "quality_label": quality.get("quality_label"),
            "page_directory": page_dir_relative,
            "content_path": f"{page_dir_relative}/{content_filename}",
            "metadata_path": f"{page_dir_relative}/{metadata_filename}",
            "images_count": len(metadata.get("images") or []),
            "pdf_count": len(documents.get("pdfs") or []),
            "file_count": len(documents.get("files") or []),
            "primary_image": metadata.get("primary_image"),
            "tags": metadata.get("tags") or [],
            "extraction_warnings": metadata.get("extraction_warnings") or [],
            "missing_fields": metadata.get("missing_fields") or [],
            "fallback_used": bool(metadata.get("fallback_used")),
            "raw_content_retained": bool(metadata.get("raw_content_retained")),
        }

    async def _load_manifest(self) -> Dict[str, Any]:
        manifest = {
            "job_id": self.job_id,
            "generated_at": None,
            "total_completed": 0,
            "records": [],
        }

        manifest_path = self.get_path()
        if not manifest_path.exists():
            return manifest

        try:
            async with aiofiles.open(manifest_path, "r", encoding="utf-8") as f:
                existing = json.loads(await f.read())
            if isinstance(existing, dict):
                manifest.update(existing)
        except Exception:
            pass

        return manifest

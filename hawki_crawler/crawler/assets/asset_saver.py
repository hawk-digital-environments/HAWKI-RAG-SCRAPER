from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from hawki_crawler.runtime.writes import AsyncFile
from hawki_crawler.runtime.writes import mkdir as guarded_mkdir


class AssetSaver:
    """Saves downloaded file bytes and builds the asset metadata entry."""

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

    async def save_file_bytes(
        self,
        *,
        file_url: str,
        filename: str,
        file_bytes: bytes,
        page_number: int,
        content_type: str,
        url_hash: Optional[str] = None,
        incomplete: bool = False,
        error: Optional[BaseException] = None,
    ) -> Dict[str, str]:
        if url_hash and self.storage_manager:
            self.storage_manager.create_hash_directory(
                url_hash,
                create_images_dir=not self.skip_images,
                create_files_dir=True,
            )
            await self.storage_manager.save_hash_pdf(url_hash, filename, file_bytes)
            files_dir = self.storage_manager.get_hash_files_directory(url_hash)
            filepath = files_dir / filename
        elif self.storage_manager:
            await self.create_page_directory(page_number, create_files_dir=True)
            await self.storage_manager.save_pdf(page_number, filename, file_bytes)
            files_dir = self.storage_manager.get_files_directory(page_number)
            filepath = files_dir / filename
        else:
            page_dir = await self.create_page_directory(page_number, create_files_dir=True)
            files_dir = page_dir / "files"
            guarded_mkdir(files_dir, exist_ok=True)
            filepath = files_dir / filename
            async with AsyncFile(filepath, "wb") as f:
                await f.write(file_bytes)

        result = {
            "url": file_url,
            "local_path": str(filepath.resolve()),
            "filename": filename,
            "relative_path": f"files/{filename}",
            "content_type": content_type,
        }
        if incomplete:
            result["incomplete"] = True
            result["error"] = str(error)
        return result

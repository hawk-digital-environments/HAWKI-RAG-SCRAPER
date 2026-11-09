from pathlib import Path
from typing import Callable

from hawki_crawler.runtime.writes import AsyncFile
from hawki_crawler.runtime.writes import mkdir as guarded_mkdir


class AssetStore:
    """Stores downloaded page assets under the existing page/hash directories."""

    def __init__(
        self,
        *,
        get_hash_directory: Callable[[str], Path],
        get_page_directory: Callable[[int], Path],
    ) -> None:
        self._get_hash_directory = get_hash_directory
        self._get_page_directory = get_page_directory

    def get_hash_images_directory(self, url_hash: str) -> Path:
        return self._get_hash_directory(url_hash) / "images"

    def get_hash_files_directory(self, url_hash: str) -> Path:
        return self._get_hash_directory(url_hash) / "files"

    def get_images_directory(self, page_number: int) -> Path:
        return self._get_page_directory(page_number) / "images"

    def get_files_directory(self, page_number: int) -> Path:
        return self._get_page_directory(page_number) / "files"

    async def save_hash_image(self, url_hash: str, filename: str, image_data: bytes) -> str:
        images_dir = self.get_hash_images_directory(url_hash)
        filepath = images_dir / filename

        async with AsyncFile(filepath, "wb") as f:
            await f.write(image_data)

        return filename

    async def save_hash_pdf(self, url_hash: str, filename: str, pdf_data: bytes) -> str:
        files_dir = self.get_hash_files_directory(url_hash)
        guarded_mkdir(files_dir, parents=True, exist_ok=True)
        filepath = files_dir / filename

        async with AsyncFile(filepath, "wb") as f:
            await f.write(pdf_data)

        return filename

    async def save_image(self, page_number: int, filename: str, image_data: bytes) -> str:
        images_dir = self.get_images_directory(page_number)
        filepath = images_dir / filename

        async with AsyncFile(filepath, "wb") as f:
            await f.write(image_data)

        return filename

    async def save_pdf(self, page_number: int, filename: str, pdf_data: bytes) -> str:
        files_dir = self.get_files_directory(page_number)
        guarded_mkdir(files_dir, parents=True, exist_ok=True)
        filepath = files_dir / filename

        async with AsyncFile(filepath, "wb") as f:
            await f.write(pdf_data)

        return filename

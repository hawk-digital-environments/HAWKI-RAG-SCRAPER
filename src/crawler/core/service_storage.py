from pathlib import Path
from typing import TYPE_CHECKING

from hawki_crawler.crawler.storage.runtime_directories import (
    create_runtime_page_directory,
    setup_output_directory,
)

if TYPE_CHECKING:
    from hawki_crawler.crawler.core.protocols import ServiceStorageMixinProtocol


class ServiceStorageMixin:
    """Compatibility mixin for crawler runtime directory helpers."""

    async def setup_directories(self: "ServiceStorageMixinProtocol") -> None:
        """Create necessary output directories."""
        await setup_output_directory(
            storage_manager=self.storage_manager,
            output_dir=self.output_dir,
        )

    async def create_page_directory(
        self: "ServiceStorageMixinProtocol",
        page_number: int,
        create_files_dir: bool = False,
    ) -> Path:
        """Create a page directory using storage manager or legacy output paths."""
        return await create_runtime_page_directory(
            storage_manager=self.storage_manager,
            output_dir=self.output_dir,
            page_number=page_number,
            skip_images=self.config.skip_images,
            create_files_dir=create_files_dir,
        )

"""Image download behavior for crawler assets."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import aiohttp

from hawki_crawler.runtime.writes import AsyncFile


class ImageDownloader:
    """Download and validate supported image assets."""

    def __init__(self, *, rate_limiter: Any, logger: Optional[Any] = None) -> None:
        self.rate_limiter = rate_limiter
        self.logger = logger or logging.getLogger("crawler")

    async def download_image(
        self,
        image_url: str,
        session: aiohttp.ClientSession,
        images_dir: Path,
    ) -> Optional[str]:
        """Download an image and save it to the images directory."""
        await self.rate_limiter.acquire()
        allowed_extensions = {".jpg", ".jpeg", ".png", ".webp"}
        allowed_content_type_to_exts = {
            "image/jpeg": (".jpg", ".jpeg"),
            "image/png": (".png",),
            "image/webp": (".webp",),
        }

        try:
            parsed_url = urlparse(image_url)
            normalized_path = (parsed_url.path or "").lower()
            normalized_query = (parsed_url.query or "").lower()
            if "piwik.php" in normalized_path or "piwik.php" in normalized_query:
                return None

            async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status != 200:
                    return None

                content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if not content_type.startswith("image/"):
                    return None
                if content_type not in allowed_content_type_to_exts:
                    return None

                filename = re.sub(r"[^a-zA-Z0-9_.-]", "_", os.path.basename(urlparse(image_url).path))
                if not filename:
                    return None
                suffix = Path(filename).suffix.lower()
                if not suffix or suffix not in allowed_extensions:
                    return None

                image_data = await response.read()

                image_path = images_dir / filename
                async with AsyncFile(image_path, "wb") as f:
                    await f.write(image_data)

                return filename
        except Exception as exc:
            self.logger.warning("Error downloading image %s: %s", image_url, exc)
            return None

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Dict, Optional, List, Tuple, TYPE_CHECKING
from urllib.parse import urlparse

import aiofiles
import aiohttp
from aiohttp.http_exceptions import ContentLengthError

from hawki_crawler.crawler.assets.asset_saver import AssetSaver
from hawki_crawler.crawler.assets.asset_policy import AssetPolicy

if TYPE_CHECKING:
    from hawki_crawler.crawler.core.protocols import ServiceParseAssetsMixinProtocol


class ServiceParseAssetsMixin:
    def _asset_policy(self) -> AssetPolicy:
        return AssetPolicy()

    def _asset_saver(self: "ServiceParseAssetsMixinProtocol") -> AssetSaver:
        return AssetSaver(
            storage_manager=getattr(self, "storage_manager", None),
            create_page_directory=self.create_page_directory,
            skip_images=getattr(self.config, "skip_images", False),
        )

    def _asset_logger(self: "ServiceParseAssetsMixinProtocol"):
        return getattr(self, "job_logger", logging.getLogger("crawler"))

    async def _publish_saved_file_event(
        self: "ServiceParseAssetsMixinProtocol",
        *,
        file_url: str,
        page_url: Optional[str],
        file_entry: Dict[str, str],
    ) -> None:
        publisher = getattr(self, "file_event_publisher", None)
        if not publisher:
            return

        if file_entry.get("incomplete"):
            return

        try:
            outcome = await publisher.publish_file_discovered(
                url=file_url,
                page_url=page_url,
                job_id=getattr(self, "job_id", None),
                local_path=file_entry.get("local_path", ""),
                relative_path=file_entry.get("relative_path"),
                filename=file_entry.get("filename"),
                extension=Path(file_entry.get("filename", "")).suffix,
                content_type=file_entry.get("content_type"),
                payload={"asset_type": "file"},
            )
            if not outcome.success and not outcome.skipped:
                self._asset_logger().error(
                    "file_event_publish_failed url=%s local_path=%s reason=%s error=%s",
                    file_url,
                    file_entry.get("local_path"),
                    outcome.reason,
                    outcome.error,
                )
        except Exception as exc:  # pragma: no cover - defensive path
            self._asset_logger().error(
                "file_event_publish_exception url=%s local_path=%s error=%s",
                file_url,
                file_entry.get("local_path"),
                exc,
            )

    async def download_image(
        self: "ServiceParseAssetsMixinProtocol",
        image_url: str,
        session: aiohttp.ClientSession,
        images_dir: Path
    ) -> Optional[str]:
        """Download an image and save it to the images directory"""
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

                content_type = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
                if not content_type.startswith('image/'):
                    return None
                if content_type not in allowed_content_type_to_exts:
                    return None

                filename = re.sub(r'[^a-zA-Z0-9\-_\.]', '_', os.path.basename(urlparse(image_url).path))
                if not filename:
                    return None
                suffix = Path(filename).suffix.lower()
                if not suffix or suffix not in allowed_extensions:
                    return None

                image_data = await response.read()

                image_path = images_dir / filename
                async with aiofiles.open(image_path, 'wb') as f:
                    await f.write(image_data)

                return filename
        except Exception as e:
            self._asset_logger().warning("Error downloading image %s: %s", image_url, e)
            return None

    def extract_pdf_links(self, html_content: str, base_url: str) -> List[str]:
        """Extract PDF links from HTML content"""
        return self._asset_policy().extract_pdf_links(html_content, base_url)

    def extract_file_links(self, html_content: str, base_url: str) -> List[str]:
        """Extract non-PDF file links from HTML content."""
        return self._asset_policy().extract_file_links(html_content, base_url)

    def _should_skip_file_download(
        self,
        url: str,
        filename: Optional[str],
        content_type: str
    ) -> bool:
        """Skip downloads that resolve to disallowed or extension-less files."""
        return self._asset_policy().should_skip_file_download(url, filename, content_type)

    async def fetch_head(self: "ServiceParseAssetsMixinProtocol", url: str) -> Tuple[Optional[int], Dict[str, str]]:
        """Fetch HEAD request for a URL"""
        await self.rate_limiter.acquire()

        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with self.http_session.head(url, allow_redirects=True, timeout=timeout) as response:
                headers = {k.lower(): v for k, v in response.headers.items()}
                return response.status, headers
        except Exception as e:
            self._asset_logger().warning("HEAD request failed for %s: %s", url, e)
            return None, {}

    async def is_pdf_resource(
        self: "ServiceParseAssetsMixinProtocol",
        url: str,
        head_status: Optional[int] = None,
        head_headers: Optional[Dict[str, str]] = None
    ) -> bool:
        """Check if a URL points directly to a PDF"""
        if self._asset_policy().is_pdf_url(url):
            return True

        headers = head_headers or await self.fetch_head(url)
        if isinstance(headers, tuple):
            headers = headers[1]
        return self._asset_policy().is_pdf_resource(url, headers if isinstance(headers, dict) else {})

    async def is_file_resource(
        self: "ServiceParseAssetsMixinProtocol",
        url: str,
        head_status: Optional[int] = None,
        head_headers: Optional[Dict[str, str]] = None
    ) -> bool:
        """Check if a URL points directly to a non-PDF file."""
        if self._asset_policy().is_file_resource(url, None):
            return True

        headers = head_headers or await self.fetch_head(url)
        if isinstance(headers, tuple):
            headers = headers[1]
        if not isinstance(headers, dict):
            return False

        return self._asset_policy().is_file_resource(url, headers)

    def _filename_from_content_disposition(self, header_value: str) -> Optional[str]:
        return self._asset_policy().filename_from_content_disposition(header_value)

    async def fetch_and_save_pdf(
        self: "ServiceParseAssetsMixinProtocol",
        pdf_url: str,
        page_number: int,
        session: Optional[aiohttp.ClientSession] = None,
        url_hash: Optional[str] = None,
        page_url: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        """Download a PDF and save it to the files directory"""
        await self.rate_limiter.acquire()

        cleanup_session = False
        if session is None:
            session = aiohttp.ClientSession(headers=self.headers)
            cleanup_session = True

        last_error = None
        max_attempts = 3
        try:
            for attempt in range(1, max_attempts + 1):
                try:
                    async with session.get(
                        pdf_url,
                        headers=self.headers,
                        timeout=aiohttp.ClientTimeout(total=60)
                    ) as response:
                        content_type = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
                        if response.status not in (200, 206) or (
                            'pdf' not in content_type and not pdf_url.lower().split('?')[0].endswith('.pdf')
                        ):
                            return None

                        pdf_buffer = bytearray()
                        incomplete = False
                        try:
                            async for chunk in response.content.iter_chunked(1024 * 256):
                                if chunk:
                                    pdf_buffer.extend(chunk)
                        except (aiohttp.ClientPayloadError, ContentLengthError) as e:
                            incomplete = True
                            last_error = e

                        if not pdf_buffer:
                            if attempt < max_attempts and last_error:
                                await asyncio.sleep(0.5 * attempt)
                                continue
                            return None

                        filename = self._asset_policy().pdf_filename_from_url(pdf_url)

                        result = await self._asset_saver().save_file_bytes(
                            file_url=pdf_url,
                            filename=filename,
                            file_bytes=bytes(pdf_buffer),
                            page_number=page_number,
                            content_type=content_type,
                            url_hash=url_hash,
                            incomplete=incomplete,
                            error=last_error,
                        )
                        if not incomplete:
                            await self._publish_saved_file_event(
                                file_url=pdf_url,
                                page_url=page_url or pdf_url,
                                file_entry=result,
                            )
                        return result
                except (aiohttp.ClientPayloadError, ContentLengthError) as e:
                    last_error = e
                    if attempt < max_attempts:
                        await asyncio.sleep(0.5 * attempt)
                        continue
                    self._asset_logger().error("Error downloading PDF %s: %s", pdf_url, e)
                    return None
                except Exception as e:
                    self._asset_logger().error("Error downloading PDF %s: %s", pdf_url, e)
                    return None
        finally:
            if cleanup_session:
                await session.close()

    async def fetch_and_save_file(
        self: "ServiceParseAssetsMixinProtocol",
        file_url: str,
        page_number: int,
        session: Optional[aiohttp.ClientSession] = None,
        url_hash: Optional[str] = None,
        page_url: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        """Download a non-PDF file and save it to the files directory."""
        await self.rate_limiter.acquire()

        cleanup_session = False
        if session is None:
            session = aiohttp.ClientSession(headers=self.headers)
            cleanup_session = True

        last_error = None
        max_attempts = 3
        try:
            for attempt in range(1, max_attempts + 1):
                try:
                    async with session.get(
                        file_url,
                        headers=self.headers,
                        timeout=aiohttp.ClientTimeout(total=60)
                    ) as response:
                        if response.status not in (200, 206):
                            return None

                        content_type = response.headers.get('Content-Type', '').split(';')[0].lower()
                        content_disposition = response.headers.get('Content-Disposition', '')

                        file_buffer = bytearray()
                        incomplete = False
                        try:
                            async for chunk in response.content.iter_chunked(1024 * 256):
                                if chunk:
                                    file_buffer.extend(chunk)
                        except (aiohttp.ClientPayloadError, ContentLengthError) as e:
                            incomplete = True
                            last_error = e

                        if not file_buffer:
                            if attempt < max_attempts and last_error:
                                await asyncio.sleep(0.5 * attempt)
                                continue
                            return None

                        filename = self._asset_policy().file_filename_from_response(
                            file_url,
                            content_type,
                            content_disposition,
                        )
                        if self._should_skip_file_download(file_url, filename, content_type):
                            return None

                        result = await self._asset_saver().save_file_bytes(
                            file_url=file_url,
                            filename=filename,
                            file_bytes=bytes(file_buffer),
                            page_number=page_number,
                            content_type=content_type,
                            url_hash=url_hash,
                            incomplete=incomplete and bool(last_error),
                            error=last_error,
                        )
                        if not (incomplete and last_error):
                            await self._publish_saved_file_event(
                                file_url=file_url,
                                page_url=page_url or file_url,
                                file_entry=result,
                            )
                        return result
                except (aiohttp.ClientPayloadError, ContentLengthError) as e:
                    last_error = e
                    if attempt < max_attempts:
                        await asyncio.sleep(0.5 * attempt)
                        continue
                    self._asset_logger().error("Error downloading file %s: %s", file_url, e)
                    return None
                except Exception as e:
                    self._asset_logger().error("Error downloading file %s: %s", file_url, e)
                    return None
        finally:
            if cleanup_session:
                await session.close()

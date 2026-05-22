import asyncio
import logging
import mimetypes
import os
import re
from pathlib import Path
from typing import Dict, Optional, List, Tuple, TYPE_CHECKING
from urllib.parse import urljoin, urlparse

import aiofiles
import aiohttp
from aiohttp.http_exceptions import ContentLengthError
from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from hawki_crawler.crawler.core.protocols import CrawlerServiceProtocol


class ServiceParseAssetsMixin:
    def _asset_logger(self: "CrawlerServiceProtocol"):
        return getattr(self, "job_logger", logging.getLogger("crawler"))

    async def _publish_saved_file_event(
        self: "CrawlerServiceProtocol",
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
        self: "CrawlerServiceProtocol",
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
        soup = BeautifulSoup(html_content, 'html.parser')
        pdf_links = []
        for a in soup.find_all('a'):
            href = a.get('href')
            if not href:
                continue
            absolute_url = urljoin(base_url, href)
            if absolute_url.lower().split('?')[0].endswith('.pdf'):
                pdf_links.append(absolute_url)
        return pdf_links

    def extract_file_links(self, html_content: str, base_url: str) -> List[str]:
        """Extract non-PDF file links from HTML content."""
        extensions = (
            ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods",
            ".odp", ".rtf", ".txt", ".csv", ".zip", ".rar", ".7z"
        )
        disallowed_extensions = (".exe",)
        soup = BeautifulSoup(html_content, 'html.parser')
        file_links = []
        for a in soup.find_all('a'):
            href = a.get('href')
            if not href:
                continue
            absolute_url = urljoin(base_url, href)
            lower = absolute_url.lower().split('?')[0]
            if lower.endswith('.pdf'):
                continue
            if lower.endswith(disallowed_extensions):
                continue
            if lower.endswith(extensions):
                file_links.append(absolute_url)
        return file_links

    def _should_skip_file_download(
        self,
        url: str,
        filename: Optional[str],
        content_type: str
    ) -> bool:
        """Skip downloads that resolve to disallowed or extension-less files."""
        parsed = urlparse(url)
        path = parsed.path.lower()
        if path.endswith(".exe"):
            return True
        if filename and filename.lower().endswith(".exe"):
            return True
        if content_type == "application/x-msdownload":
            return True
        if not filename:
            return True
        if Path(filename).suffix == "":
            return True
        return False

    async def fetch_head(self: "CrawlerServiceProtocol", url: str) -> Tuple[Optional[int], Dict[str, str]]:
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
        self: "CrawlerServiceProtocol",
        url: str,
        head_status: Optional[int] = None,
        head_headers: Optional[Dict[str, str]] = None
    ) -> bool:
        """Check if a URL points directly to a PDF"""
        if url.lower().split('?')[0].endswith('.pdf'):
            return True

        headers = head_headers or await self.fetch_head(url)
        if isinstance(headers, tuple):
            headers = headers[1]
        content_type = headers.get('content-type', '') if isinstance(headers, dict) else ''
        return 'pdf' in content_type.lower()

    async def is_file_resource(
        self: "CrawlerServiceProtocol",
        url: str,
        head_status: Optional[int] = None,
        head_headers: Optional[Dict[str, str]] = None
    ) -> bool:
        """Check if a URL points directly to a non-PDF file."""
        parsed = urlparse(url)
        path = parsed.path.lower()
        if path.endswith(".exe"):
            return False
        if "/media/" in path and not path.endswith(".pdf"):
            return True

        extensions = (
            ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods",
            ".odp", ".rtf", ".txt", ".csv", ".zip", ".rar", ".7z"
        )
        if path.endswith(extensions):
            return True

        headers = head_headers or await self.fetch_head(url)
        if isinstance(headers, tuple):
            headers = headers[1]
        if not isinstance(headers, dict):
            return False

        content_type = headers.get('content-type', '').lower()
        if not content_type:
            return False
        if content_type == "application/x-msdownload":
            return False
        if 'text/html' in content_type:
            return False
        if content_type.startswith('image/'):
            return False
        if content_type in ("text/css", "text/javascript", "application/javascript"):
            return False
        if 'application/' in content_type or 'octet-stream' in content_type:
            return True

        content_disposition = headers.get('content-disposition', '').lower()
        return 'attachment' in content_disposition

    def _filename_from_content_disposition(self, header_value: str) -> Optional[str]:
        if not header_value:
            return None
        match = re.search(r"filename\\*?=(?:UTF-8''|\\\")?([^\\\";]+)", header_value, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    async def fetch_and_save_pdf(
        self: "CrawlerServiceProtocol",
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

                        parsed = urlparse(pdf_url)
                        filename = os.path.basename(parsed.path)
                        if not filename or not filename.lower().endswith('.pdf'):
                            filename = f"file_{abs(hash(pdf_url))}.pdf"

                        umlaut_map = str.maketrans({
                            'ä': 'ae', 'ö': 'oe', 'ü': 'ue',
                            'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue',
                            'ß': 'ss'
                        })
                        filename = filename.translate(umlaut_map)
                        filename = re.sub(r'[^\w\-_\.]', '_', filename)

                        pdf_bytes = bytes(pdf_buffer)

                        if url_hash and self.storage_manager:
                            self.storage_manager.create_hash_directory(
                                url_hash,
                                create_images_dir=not self.config.skip_images,
                                create_files_dir=True
                            )
                            await self.storage_manager.save_hash_pdf(url_hash, filename, pdf_bytes)
                            files_dir = self.storage_manager.get_hash_files_directory(url_hash)
                            filepath = files_dir / filename
                        elif self.storage_manager:
                            page_dir = await self.create_page_directory(page_number, create_files_dir=True)
                            await self.storage_manager.save_pdf(page_number, filename, pdf_bytes)
                            files_dir = self.storage_manager.get_files_directory(page_number)
                            filepath = files_dir / filename
                        else:
                            page_dir = await self.create_page_directory(page_number, create_files_dir=True)
                            files_dir = page_dir / "files"
                            files_dir.mkdir(exist_ok=True)
                            filepath = files_dir / filename
                            async with aiofiles.open(filepath, 'wb') as f:
                                await f.write(pdf_bytes)

                        result = {
                            "url": pdf_url,
                            "local_path": str(filepath.resolve()),
                            "filename": filename,
                            "relative_path": f"files/{filename}",
                            "content_type": content_type,
                        }
                        if incomplete:
                            result["incomplete"] = True
                            result["error"] = str(last_error)
                        else:
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
        self: "CrawlerServiceProtocol",
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

                        filename = self._filename_from_content_disposition(content_disposition)
                        if not filename:
                            parsed = urlparse(file_url)
                            filename = os.path.basename(parsed.path)
                        if not filename:
                            ext = mimetypes.guess_extension(content_type or "")
                            ext = ext or ".bin"
                            filename = f"file_{abs(hash(file_url))}{ext}"
                        if self._should_skip_file_download(file_url, filename, content_type):
                            return None

                        umlaut_map = str.maketrans({
                            'ä': 'ae', 'ö': 'oe', 'ü': 'ue',
                            'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue',
                            'ß': 'ss'
                        })
                        filename = filename.translate(umlaut_map)
                        filename = re.sub(r'[^A-Za-z0-9._-]', '_', filename)

                        file_bytes = bytes(file_buffer)

                        if url_hash and self.storage_manager:
                            self.storage_manager.create_hash_directory(
                                url_hash,
                                create_images_dir=not self.config.skip_images,
                                create_files_dir=True
                            )
                            await self.storage_manager.save_hash_pdf(url_hash, filename, file_bytes)
                            files_dir = self.storage_manager.get_hash_files_directory(url_hash)
                            filepath = files_dir / filename
                        elif self.storage_manager:
                            page_dir = await self.create_page_directory(page_number, create_files_dir=True)
                            await self.storage_manager.save_pdf(page_number, filename, file_bytes)
                            files_dir = self.storage_manager.get_files_directory(page_number)
                            filepath = files_dir / filename
                        else:
                            page_dir = await self.create_page_directory(page_number, create_files_dir=True)
                            files_dir = page_dir / "files"
                            files_dir.mkdir(exist_ok=True)
                            filepath = files_dir / filename
                            async with aiofiles.open(filepath, 'wb') as f:
                                await f.write(file_bytes)

                        result = {
                            "url": file_url,
                            "local_path": str(filepath.resolve()),
                            "filename": filename,
                            "relative_path": f"files/{filename}",
                            "content_type": content_type
                        }
                        if incomplete and last_error:
                            result["incomplete"] = True
                            result["error"] = str(last_error)
                        else:
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

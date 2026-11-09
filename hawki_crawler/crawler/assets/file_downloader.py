"""PDF and generic file download behavior for crawler assets."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

import aiohttp
from aiohttp.http_exceptions import ContentLengthError

from hawki_crawler.crawler.assets.asset_saver import AssetSaver
from hawki_crawler.crawler.parsing.resource_parser import ResourceParser
from hawki_crawler.crawler.policies.resource_policy import ResourcePolicy
from hawki_crawler.runtime.network import SafeSession


class FileDownloader:
    """Download PDFs and supported files, then persist them."""

    def __init__(
        self,
        *,
        rate_limiter: Any,
        headers: Dict[str, str],
        asset_saver: AssetSaver,
        logger: Optional[Any] = None,
        resource_policy: Optional[ResourcePolicy] = None,
        resource_parser: Optional[ResourceParser] = None,
        policy: Optional[ResourcePolicy] = None,
    ) -> None:
        self.rate_limiter = rate_limiter
        self.headers = headers
        self.asset_saver = asset_saver
        self.logger = logger or logging.getLogger("crawler")
        self.resource_policy = resource_policy or policy or ResourcePolicy()
        self.resource_parser = resource_parser or ResourceParser(self.resource_policy)

    async def fetch_and_save_pdf(
        self,
        pdf_url: str,
        page_number: int,
        session: Optional[aiohttp.ClientSession] = None,
        url_hash: Optional[str] = None,
        page_url: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        """Download a PDF and save it to the files directory."""
        await self.rate_limiter.acquire()

        cleanup_session = False
        if session is None:
            session = SafeSession(headers=self.headers)
            cleanup_session = True

        last_error = None
        max_attempts = 3
        try:
            for attempt in range(1, max_attempts + 1):
                try:
                    async with session.get(
                        pdf_url,
                        headers=self.headers,
                        timeout=aiohttp.ClientTimeout(total=60),
                    ) as response:
                        content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                        if response.status not in (200, 206) or not self.resource_policy.is_pdf_resource(
                            pdf_url,
                            {"content-type": content_type},
                        ):
                            return None

                        pdf_buffer = bytearray()
                        incomplete = False
                        try:
                            async for chunk in response.content.iter_chunked(1024 * 256):
                                if chunk:
                                    pdf_buffer.extend(chunk)
                        except (aiohttp.ClientPayloadError, ContentLengthError) as exc:
                            incomplete = True
                            last_error = exc

                        if not pdf_buffer:
                            if attempt < max_attempts and last_error:
                                await asyncio.sleep(0.5 * attempt)
                                continue
                            return None

                        filename = self.resource_parser.pdf_filename_from_url(pdf_url)

                        result = await self.asset_saver.save_file_bytes(
                            file_url=pdf_url,
                            filename=filename,
                            file_bytes=bytes(pdf_buffer),
                            page_number=page_number,
                            content_type=content_type,
                            url_hash=url_hash,
                            incomplete=incomplete,
                            error=last_error,
                        )
                        return result
                except (aiohttp.ClientPayloadError, ContentLengthError) as exc:
                    last_error = exc
                    if attempt < max_attempts:
                        await asyncio.sleep(0.5 * attempt)
                        continue
                    self.logger.error("Error downloading PDF %s: %s", pdf_url, exc)
                    return None
                except Exception as exc:
                    self.logger.error("Error downloading PDF %s: %s", pdf_url, exc)
                    return None
        finally:
            if cleanup_session:
                await session.close()

    async def fetch_and_save_file(
        self,
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
            session = SafeSession(headers=self.headers)
            cleanup_session = True

        last_error = None
        max_attempts = 3
        try:
            for attempt in range(1, max_attempts + 1):
                try:
                    async with session.get(
                        file_url,
                        headers=self.headers,
                        timeout=aiohttp.ClientTimeout(total=60),
                    ) as response:
                        if response.status not in (200, 206):
                            return None

                        content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
                        content_disposition = response.headers.get("Content-Disposition", "")

                        file_buffer = bytearray()
                        incomplete = False
                        try:
                            async for chunk in response.content.iter_chunked(1024 * 256):
                                if chunk:
                                    file_buffer.extend(chunk)
                        except (aiohttp.ClientPayloadError, ContentLengthError) as exc:
                            incomplete = True
                            last_error = exc

                        if not file_buffer:
                            if attempt < max_attempts and last_error:
                                await asyncio.sleep(0.5 * attempt)
                                continue
                            return None

                        filename = self.resource_parser.file_filename_from_response(
                            file_url,
                            content_type,
                            content_disposition,
                        )
                        if self.resource_policy.should_skip_file_download(
                            file_url,
                            filename,
                            content_type,
                        ):
                            return None

                        result = await self.asset_saver.save_file_bytes(
                            file_url=file_url,
                            filename=filename,
                            file_bytes=bytes(file_buffer),
                            page_number=page_number,
                            content_type=content_type,
                            url_hash=url_hash,
                            incomplete=incomplete and bool(last_error),
                            error=last_error,
                        )
                        return result
                except (aiohttp.ClientPayloadError, ContentLengthError) as exc:
                    last_error = exc
                    if attempt < max_attempts:
                        await asyncio.sleep(0.5 * attempt)
                        continue
                    self.logger.error("Error downloading file %s: %s", file_url, exc)
                    return None
                except Exception as exc:
                    self.logger.error("Error downloading file %s: %s", file_url, exc)
                    return None
        finally:
            if cleanup_session:
                await session.close()

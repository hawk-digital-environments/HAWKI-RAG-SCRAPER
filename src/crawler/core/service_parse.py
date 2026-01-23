import asyncio
import hashlib
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List, Tuple
from urllib.parse import urljoin, urlparse

import aiofiles
import aiohttp
from aiohttp.http_exceptions import ContentLengthError
from bs4 import BeautifulSoup
import html2text
from crawl4ai import AsyncWebCrawler
from crawl4ai.async_configs import CrawlerRunConfig, CacheMode

from src.crawler.core.service_helpers import clean_html_for_markdown, filter_markdown_lines
from src.crawler.core.service_utils import assess_content_quality


class ServiceParseMixin:
    async def download_image(self, image_url: str, session: aiohttp.ClientSession, images_dir: Path) -> Optional[str]:
        """Download an image and save it to the images directory"""
        await self.rate_limiter.acquire()

        try:
            async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status != 200:
                    return None

                content_type = response.headers.get('Content-Type', '').lower()
                if 'image' not in content_type:
                    return None

                image_data = await response.read()
                filename = re.sub(r'[^a-zA-Z0-9\-_\.]', '_', os.path.basename(urlparse(image_url).path))
                if not filename:
                    filename = f"image_{abs(hash(image_url))}.jpg"

                image_path = images_dir / filename
                async with aiofiles.open(image_path, 'wb') as f:
                    await f.write(image_data)

                return filename
        except Exception as e:
            print(f"Error downloading image {image_url}: {e}")
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

    async def fetch_head(self, url: str) -> Tuple[Optional[int], Dict[str, str]]:
        """Fetch HEAD request for a URL"""
        await self.rate_limiter.acquire()

        try:
            async with self.http_session.head(url, allow_redirects=True) as response:
                headers = {k.lower(): v for k, v in response.headers.items()}
                return response.status, headers
        except Exception:
            return None, {}

    async def is_pdf_resource(
        self,
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

    async def fetch_and_save_pdf(
        self,
        pdf_url: str,
        page_number: int,
        session: Optional[aiohttp.ClientSession] = None,
        url_hash: Optional[str] = None
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
                        content_type = response.headers.get('Content-Type', '').lower()
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

                        # Normalize German characters and sanitize
                        umlaut_map = str.maketrans({
                            'ä': 'ae', 'ö': 'oe', 'ü': 'ue',
                            'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue',
                            'ß': 'ss'
                        })
                        filename = filename.translate(umlaut_map)
                        filename = re.sub(r'[^\w\-_\.]', '_', filename)

                        pdf_bytes = bytes(pdf_buffer)

                        # Use hash-based or page number-based storage
                        if url_hash and self.storage_manager:
                            # Hash-based storage
                            self.storage_manager.create_hash_directory(
                                url_hash,
                                create_images_dir=not self.config.skip_images,
                                create_files_dir=True
                            )
                            await self.storage_manager.save_hash_pdf(url_hash, filename, pdf_bytes)
                            files_dir = self.storage_manager.get_hash_files_directory(url_hash)
                            filepath = files_dir / filename
                        elif self.storage_manager:
                            # Page number-based storage (deprecated)
                            page_dir = await self.create_page_directory(page_number, create_files_dir=True)
                            await self.storage_manager.save_pdf(page_number, filename, pdf_bytes)
                            files_dir = self.storage_manager.get_files_directory(page_number)
                            filepath = files_dir / filename
                        else:
                            # Fallback for no storage_manager
                            page_dir = await self.create_page_directory(page_number, create_files_dir=True)
                            files_dir = page_dir / "files"
                            files_dir.mkdir(exist_ok=True)
                            filepath = files_dir / filename
                            async with aiofiles.open(filepath, 'wb') as f:
                                await f.write(pdf_bytes)

                        result = {
                            "url": pdf_url,
                            "local_path": str(filepath.resolve())
                        }
                        if incomplete:
                            result["incomplete"] = True
                            result["error"] = str(last_error)
                        return result
                except (aiohttp.ClientPayloadError, ContentLengthError) as e:
                    last_error = e
                    if attempt < max_attempts:
                        await asyncio.sleep(0.5 * attempt)
                        continue
                    print(f"Error downloading PDF {pdf_url}: {e}")
                    return None
                except Exception as e:
                    print(f"Error downloading PDF {pdf_url}: {e}")
                    return None
        finally:
            if cleanup_session:
                await session.close()

    async def extract_page_data(
        self,
        url: str,
        crawler: AsyncWebCrawler,
        page_number: int,
        head_headers: Optional[Dict[str, str]] = None,
        head_status: Optional[int] = None,
        depth: int = 0,
        source_type: str = "seed",
        url_hash: Optional[str] = None
    ) -> Optional[Dict]:
        """Extract data from a single page"""
        await self.rate_limiter.acquire()

        try:
            run_config = CrawlerRunConfig(
                word_count_threshold=0,
                exclude_external_links=False,
                process_iframes=False,
                remove_overlay_elements=False,
                cache_mode=CacheMode.BYPASS,
                wait_until=self.config.wait_until,
                page_timeout=self.config.page_timeout_ms,
                delay_before_return_html=5.0
            )

            result = await crawler.arun(url=url, config=run_config)

            # Track request
            if self.progress_tracker:
                await self.progress_tracker.increment_requests()

            if not result.success:
                print(f"Failed to crawl {url}: {result.error_message}")
                if self.progress_tracker:
                    await self.progress_tracker.increment_errors()
                return None

            cleaned_html = clean_html_for_markdown(
                result.html,
                max_link_density=self.config.max_link_density,
                max_link_density_words=self.config.max_link_density_words
            )

            h = html2text.HTML2Text()
            h.ignore_links = False
            h.body_width = 0
            h.ignore_images = False
            markdown_content = h.handle(cleaned_html)

            if not markdown_content or len(markdown_content.strip()) <= 1:
                print(f"Warning: html2text produced empty output, using BeautifulSoup text extraction for {url}")
                soup_temp = BeautifulSoup(cleaned_html, 'html.parser')
                main_content = soup_temp.find('body') or soup_temp
                text_content = main_content.get_text(separator='\n', strip=True)
                lines = [line.strip() for line in text_content.split('\n') if line.strip()]
                markdown_content = '\n\n'.join(lines)

            markdown_content = filter_markdown_lines(markdown_content)
            quality = assess_content_quality(markdown_content, self.config.min_word_count)
            low_quality_content = None
            if quality["is_low_quality"]:
                low_quality_content = markdown_content
                markdown_content = ""

            soup = BeautifulSoup(result.html, 'html.parser')

            # Extract title and Canonical URL
            title = []
            title_tag = soup.find('title')
            if title_tag:
                title.append(title_tag.text.strip())
            canonical_url = None
            canonical_tag = soup.find('link', rel='canonical')
            if canonical_tag and canonical_tag.get('href'):
                canonical_url = urljoin(url, canonical_tag['href'])

            # Final URL from result object if available
            final_url = getattr(result, 'final_url', None) or getattr(result, 'page_url', None) or url

            # Extract meta image
            meta_img_url = []
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                meta_img_url.append(og_image['content'])

            final_url = getattr(result, 'final_url', None) or getattr(result, 'page_url', None)
            entry = self._first_sitemap_entry(url, final_url)

            lang = self.detect_language(result.html, head_headers, url=final_url or url, sitemap_entry=entry)
            sitemap_date = entry.get("last_modified") if entry else None
            published_at = sitemap_date
            updated_at = sitemap_date

            # Extract images - use both crawl4ai and BeautifulSoup
            images = []
            if not self.config.skip_images:
                image_exceptions = []
                if self.config.image_exceptions:
                    image_exceptions = [s.strip() for s in self.config.image_exceptions.split(',')]

                for img in (result.media or {}).get('images', []):
                    img_src = img.get('src', '')
                    if img_src:
                        should_exclude = False
                        if image_exceptions:
                            for exception in image_exceptions:
                                if soup.find(exception):
                                    matching_imgs = soup.select(f"{exception} img")
                                    for match_img in matching_imgs:
                                        if match_img.get('src') == img_src:
                                            should_exclude = True
                                            break

                        if not should_exclude:
                            absolute_img_url = urljoin(url, img_src)
                            if not urlparse(absolute_img_url).path.lower().endswith("piwik.php"):
                                images.append(absolute_img_url)

                if len(images) == 0:
                    img_tags = soup.find_all('img')
                    for img_tag in img_tags:
                        img_src = img_tag.get('src') or img_tag.get('data-src') or img_tag.get('data-lazy-src')
                        if img_src and img_src.startswith(('http', '/')):
                            if not img_src.startswith('data:'):
                                absolute_img_url = urljoin(url, img_src)
                                if absolute_img_url not in images:
                                    images.append(absolute_img_url)

            # Download images to hash-based directory
            downloaded_images = []
            if images and not self.config.skip_images:
                if url_hash and self.storage_manager:
                    self.storage_manager.create_hash_directory(url_hash, create_images_dir=True)
                    images_dir = self.storage_manager.get_hash_images_directory(url_hash)
                else:
                    page_dir = await self.create_page_directory(page_number)
                    images_dir = page_dir / "images"

                async with aiohttp.ClientSession(headers=self.headers) as session:
                    for img_url in images:
                        filename = await self.download_image(img_url, session, images_dir)
                        if filename:
                            downloaded_images.append(filename)

            content_for_hash = markdown_content if markdown_content else result.html
            content_hash = hashlib.sha256(content_for_hash.encode('utf-8', errors='ignore')).hexdigest()

            fetch_time = datetime.now().isoformat()
            if not sitemap_date:
                published_at = fetch_time
                updated_at = fetch_time

            content_length = len((result.html or "")) if result and result.html else None

            page_data = {
                'title': title,
                'page_url': [url],
                'url_hash': url_hash,
                'canonical_url': canonical_url,
                'meta_img_url': meta_img_url,
                'images': downloaded_images if not self.config.skip_images else images,
                'lang': lang,
                'published_at': published_at,
                'updated_at': updated_at,
                'http_status': head_status,
                'content_length': content_length,
                'fetch_time': fetch_time,
                'content_hash': content_hash,
                'quality': quality
            }

            return {
                'data': page_data,
                'markdown': markdown_content,
                'low_quality_content': low_quality_content,
                'html_content': result.html
            }

        except Exception as e:
            error_text = str(e)
            if "Browser.new_context" in error_text and "Target page, context or browser has been closed" in error_text:
                raise RuntimeError(f"browser_closed:{url}") from e
            print(f"Error extracting data from {url}: {e}")
            return None

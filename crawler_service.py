import asyncio
import json
import os
import re
import hashlib
import time
from datetime import datetime
from pathlib import Path
from typing import List, Set, Dict, Optional, Any
from urllib.parse import urljoin, urlparse, urlunparse
from bs4 import BeautifulSoup
import aiohttp
import aiofiles
import html2text
from email.utils import parsedate_to_datetime
from crawl4ai import AsyncWebCrawler
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig, CacheMode

from models import CrawlConfig
from services.progress_tracker import ProgressTracker
from services.url_tracking_manager import URLTrackingManager
from services.summary_manager import SummaryManager


class RateLimiter:
    """Rate limiter to control request frequency"""

    def __init__(self, max_rpm: int, request_delay: Optional[int] = None):
        self.max_rpm = max_rpm
        self.request_delay = request_delay / 1000 if request_delay else None
        self.min_interval = 60 / max_rpm if not request_delay else None
        self.last_request_time = 0
        self.lock = asyncio.Lock()

    async def acquire(self):
        """Wait until it's safe to make another request"""
        async with self.lock:
            current_time = time.time()

            if self.request_delay:
                time_since_last = current_time - self.last_request_time
                if time_since_last < self.request_delay:
                    await asyncio.sleep(self.request_delay - time_since_last)
            elif self.min_interval:
                time_since_last = current_time - self.last_request_time
                if time_since_last < self.min_interval:
                    await asyncio.sleep(self.min_interval - time_since_last)

            self.last_request_time = time.time()


class CrawlerService:
    """Main crawler service handling all crawling operations"""

    def __init__(self, config: CrawlConfig, job_id: Optional[str] = None,
                 event_emitter: Optional[Any] = None,
                 job_state_manager: Optional[Any] = None,
                 storage_manager: Optional[Any] = None):
        """
        Initialize crawler service.

        Args:
            config: Crawl configuration
            job_id: Unique job identifier (generated if not provided)
            event_emitter: Optional EventEmitter for real-time updates
            job_state_manager: Optional JobStateManager for state tracking
            storage_manager: Optional StorageManager for file operations
        """
        self.config = config
        self.visited_urls: Set[str] = set()
        self.to_visit: List[str] = []
        self.url_depth: Dict[str, int] = {}
        self.url_source: Dict[str, str] = {}
        self.sitemap_lastmod: Dict[str, str] = {}
        self.pages_data: List[Dict] = []
        self.rate_limiter = RateLimiter(config.max_rpm, config.request_delay)
        self.semaphore = asyncio.Semaphore(config.max_concurrency)
        self.page_counter = 0
        self.counter_lock = asyncio.Lock()  # Lock for thread-safe counter operations

        # Service layer components (optional - for event tracking and state management)
        self.event_emitter = event_emitter
        self.job_state_manager = job_state_manager
        self.storage_manager = storage_manager
        self.job_id = job_id

        # Initialize new tracking systems (only if job_id is provided)
        self.progress_tracker = None
        self.url_tracking_manager = None
        self.summary_manager = None

        if self.job_id and self.storage_manager:
            # Use storage_manager's base path
            base_path = str(self.storage_manager.base_path)
            self.progress_tracker = ProgressTracker(event_emitter=event_emitter)
            self.url_tracking_manager = URLTrackingManager(job_id=job_id, base_path=base_path)
            self.summary_manager = SummaryManager(job_id=job_id, base_path=base_path)

        # HTTP headers to avoid being blocked
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }

        # Generate label if not provided (for backwards compatibility)
        if not config.label:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            domain = urlparse(str(config.url)).netloc.replace(".", "_")
            self.config.label = f"{domain}_{timestamp}"

        # Setup output directory
        # If storage_manager is provided, use its job directory
        # Otherwise, use traditional output_dir structure (backwards compatible)
        if self.storage_manager:
            self.output_dir = self.storage_manager.get_job_directory()
        else:
            self.output_dir = Path(config.output_dir) / self.config.label

    async def setup_directories(self):
        """Create necessary directories"""
        if self.storage_manager:
            self.storage_manager.ensure_job_directory()
        else:
            self.output_dir.mkdir(parents=True, exist_ok=True)

    async def create_page_directory(self, page_number: int, create_files_dir: bool = False) -> Path:
        """Create directory for a specific page"""
        if self.storage_manager:
            return self.storage_manager.create_page_directory(
                page_number,
                create_images_dir=not self.config.skip_images,
                create_files_dir=create_files_dir
            )
        else:
            # Original logic for backwards compatibility
            page_dir = self.output_dir / f"page_{page_number:05d}"
            page_dir.mkdir(exist_ok=True)

            if not self.config.skip_images:
                images_dir = page_dir / "images"
                images_dir.mkdir(exist_ok=True)

            if create_files_dir:
                files_dir = page_dir / "files"
                files_dir.mkdir(exist_ok=True)

            return page_dir

    def normalize_url(self, url: str) -> str:
        """Normalize URL by removing fragments and trailing slashes"""
        parsed = urlparse(url)
        normalized = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip('/') or '/',
            parsed.params,
            parsed.query,
            ''  # Remove fragment
        ))
        return normalized

    async def is_sitemap(self, url: str) -> bool:
        """Check if URL is a sitemap"""
        url_lower = url.lower()
        if 'sitemap' in url_lower or url_lower.endswith('.xml'):
            return True

        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.head(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    content_type = response.headers.get('Content-Type', '')
                    if 'xml' in content_type.lower():
                        return True
        except Exception:
            pass

        return False

    async def parse_sitemap(self, sitemap_url: str) -> List[str]:
        """Parse sitemap and extract URLs"""
        urls = []
        urls_with_dates = {}  # Track URLs with their dates for URLTrackingManager

        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(sitemap_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status != 200:
                        print(f"Error fetching sitemap {sitemap_url}: HTTP {response.status}")
                        return urls

                    content = await response.text()
                    soup = BeautifulSoup(content, 'xml')

                    # Handle sitemap index
                    sitemap_tags = soup.find_all('sitemap')
                    if sitemap_tags:
                        for sitemap in sitemap_tags:
                            loc = sitemap.find('loc')
                            if loc:
                                nested_urls = await self.parse_sitemap(loc.text)
                                urls.extend(nested_urls)

                    # Handle URL entries
                    url_tags = soup.find_all('url')
                    for url_tag in url_tags:
                        loc = url_tag.find('loc')
                        if loc:
                            url = loc.text
                            if urlparse(url).path.lower().endswith("piwik.php"):
                                continue
                            urls.append(url)

                            # Extract lastmod if available
                            lastmod_tag = url_tag.find('lastmod')
                            lastmod_date = None
                            if lastmod_tag and lastmod_tag.text:
                                lastmod_date = lastmod_tag.text.strip()
                                self.sitemap_lastmod[url] = lastmod_date

                            # Store for URLTrackingManager
                            urls_with_dates[url] = lastmod_date

        except Exception as e:
            print(f"Error parsing sitemap {sitemap_url}: {e}")

        # Save URLs to URLTrackingManager if available
        if self.url_tracking_manager and urls_with_dates:
            await self.url_tracking_manager.add_urls_from_sitemap(urls_with_dates)

        return urls

    async def discover_urls(self, html_content: str, base_url: str) -> List[str]:
        """Discover URLs from HTML content"""
        urls = []
        soup = BeautifulSoup(html_content, 'html.parser')
        base_domain = urlparse(base_url).netloc

        for link in soup.find_all('a', href=True):
            href = link['href']
            absolute_url = urljoin(base_url, href)
            parsed = urlparse(absolute_url)

            # Only include URLs from the same domain
            if parsed.netloc == base_domain and parsed.scheme in ['http', 'https']:
                normalized = self.normalize_url(absolute_url)
                if not urlparse(normalized).path.lower().endswith("piwik.php"):
                    urls.append(normalized)

        return urls

    async def download_image(self, image_url: str, session: aiohttp.ClientSession, images_dir: Path) -> Optional[str]:
        """Download image and return local filename"""
        # Skip downloading tracking pixels like piwik.php
        if urlparse(image_url).path.lower().endswith("piwik.php"):
            return None
        try:
            async with session.get(image_url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    # Generate filename from URL
                    parsed = urlparse(image_url)
                    filename = os.path.basename(parsed.path)
                    if not filename or '.' not in filename:
                        filename = f"image_{abs(hash(image_url))}.jpg"

                    # Sanitize filename
                    filename = re.sub(r'[^\w\-_\.]', '_', filename)
                    filepath = images_dir / filename

                    # Save image
                    content = await response.read()
                    async with aiofiles.open(filepath, 'wb') as f:
                        await f.write(content)

                    return filename
        except Exception as e:
            print(f"Error downloading image {image_url}: {e}")

        return None

    def extract_pdf_links(self, html_content: str, base_url: str) -> List[str]:
        """Extract PDF links from HTML content"""
        if not html_content:
            return []

        soup = BeautifulSoup(html_content, 'html.parser')
        pdf_urls = set()

        for link in soup.find_all('a', href=True):
            href = link['href']
            if href.lower().split('?')[0].endswith('.pdf'):
                absolute_url = urljoin(base_url, href)
                pdf_urls.add(self.normalize_url(absolute_url))

        return list(pdf_urls)

    async def fetch_head(self, url: str) -> (Optional[int], Dict[str, str]):
        """Fetch HEAD headers for a URL to detect content-type, etag, last-modified."""
        await self.rate_limiter.acquire()
        headers: Dict[str, str] = {}
        status_code: Optional[int] = None
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.head(url, timeout=aiohttp.ClientTimeout(total=10), allow_redirects=True) as response:
                    status_code = response.status
                    headers = {k.lower(): v for k, v in response.headers.items()}

                    # Track request
                    if self.progress_tracker:
                        await self.progress_tracker.increment_requests()
        except Exception:
            if self.progress_tracker:
                await self.progress_tracker.increment_errors()
        return status_code, headers

    async def is_pdf_resource(self, url: str, head_status: Optional[int] = None, head_headers: Optional[Dict[str, str]] = None) -> bool:
        """Check if a URL points directly to a PDF"""
        if url.lower().split('?')[0].endswith('.pdf'):
            return True

        headers = head_headers or await self.fetch_head(url)
        if isinstance(headers, tuple):
            # backward compatibility; should not happen after refactor
            headers = headers[1]
        content_type = headers.get('content-type', '') if isinstance(headers, dict) else ''
        return 'pdf' in content_type.lower()

    async def fetch_and_save_pdf(self, pdf_url: str, page_number: int, session: Optional[aiohttp.ClientSession] = None) -> Optional[Dict[str, str]]:
        """Download a PDF and save it to the files directory"""
        await self.rate_limiter.acquire()

        cleanup_session = False
        if session is None:
            session = aiohttp.ClientSession(headers=self.headers)
            cleanup_session = True

        try:
            async with session.get(pdf_url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=60)) as response:
                content_type = response.headers.get('Content-Type', '').lower()
                if response.status != 200 or ('pdf' not in content_type and not pdf_url.lower().split('?')[0].endswith('.pdf')):
                    return None

                pdf_bytes = await response.read()

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

                # Ensure page directory and files subdir exist
                page_dir = await self.create_page_directory(page_number, create_files_dir=True)
                files_dir = page_dir / "files"

                if self.storage_manager:
                    await self.storage_manager.save_pdf(page_number, filename, pdf_bytes)
                    files_dir = self.storage_manager.get_files_directory(page_number)
                    filepath = files_dir / filename
                else:
                    files_dir.mkdir(exist_ok=True)
                    filepath = files_dir / filename
                    async with aiofiles.open(filepath, 'wb') as f:
                        await f.write(pdf_bytes)

                return {
                    "url": pdf_url,
                    "local_path": str(filepath.resolve())
                }
        except Exception as e:
            print(f"Error downloading PDF {pdf_url}: {e}")
            return None
        finally:
            if cleanup_session:
                await session.close()

    def parse_date_string(self, date_str: str) -> Optional[str]:
        """Parse a date string into ISO format if plausible."""
        if not date_str:
            return None
        cleaned = date_str.strip()
        if not cleaned:
            return None

        # Try ISO-like
        try:
            dt = datetime.fromisoformat(cleaned.replace('Z', '+00:00'))
            if 1990 <= dt.year <= datetime.now().year + 1:
                return dt.isoformat()
        except Exception:
            pass

        # Try RFC822/HTTP style
        try:
            dt = parsedate_to_datetime(cleaned)
            if dt and 1990 <= dt.year <= datetime.now().year + 1:
                return dt.isoformat()
        except Exception:
            pass

        return None

    def detect_language(self, html_content: Optional[str], head_headers: Optional[Dict[str, str]]) -> Optional[str]:
        """
        Infer page language from HTML lang attributes or Content-Language header.
        Returns a lowercased language code when found, otherwise None.
        """
        # From headers
        if head_headers:
            content_lang = head_headers.get('content-language')
            if content_lang:
                lang_val = content_lang.split(',')[0].split(';')[0].strip().lower()
                if lang_val:
                    return lang_val

        # From HTML
        if html_content:
            soup = BeautifulSoup(html_content, 'html.parser')
            html_tag = soup.find('html')
            if html_tag and html_tag.get('lang'):
                lang_val = html_tag.get('lang').split('-')[0].strip().lower()
                if lang_val:
                    return lang_val

            meta_lang = soup.find('meta', attrs={'http-equiv': 'Content-Language'})
            if meta_lang and meta_lang.get('content'):
                lang_val = meta_lang.get('content').split(',')[0].split(';')[0].strip().lower()
                if lang_val:
                    return lang_val

        return None

    def extract_dates(self, html_content: str, soup: BeautifulSoup) -> Dict[str, Optional[str]]:
        """
        Collects dates in a deterministic order: JSON-LD (datePublished/dateModified), meta tags (og/article/date/lastmod variants), <time> tags, then elements with date-ish class names. Each candidate is normalized to ISO when plausible. Returns best-effort published/updated timestamps for downstream freshness logic.
        """
        published = None
        updated = None

        def pick(first: Optional[str], second: Optional[str]) -> Optional[str]:
            return first or second

        # JSON-LD
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
            except Exception:
                continue

            candidates = []
            if isinstance(data, list):
                candidates.extend(data)
            elif isinstance(data, dict):
                candidates.append(data)

            for item in candidates:
                if not isinstance(item, dict):
                    continue
                pub = self.parse_date_string(str(item.get('datePublished', '')).strip()) if item.get('datePublished') else None
                mod = self.parse_date_string(str(item.get('dateModified', '')).strip()) if item.get('dateModified') else None
                published = pick(published, pub)
                updated = pick(updated, mod)
                if published and updated:
                    break

        # Meta tags
        meta_map = {
            'article:published_time': 'published',
            'article:modified_time': 'updated',
            'og:updated_time': 'updated',
            'og:published_time': 'published',
            'date': 'published',
            'lastmod': 'updated'
        }
        for prop, target in meta_map.items():
            meta_tag = soup.find('meta', attrs={'property': prop}) or soup.find('meta', attrs={'name': prop})
            if meta_tag and meta_tag.get('content'):
                parsed = self.parse_date_string(meta_tag['content'])
                if target == 'published':
                    published = pick(published, parsed)
                else:
                    updated = pick(updated, parsed)

        # <time> tags
        for time_tag in soup.find_all('time'):
            dt_attr = time_tag.get('datetime') or time_tag.get('content')
            parsed = self.parse_date_string(dt_attr or time_tag.text)
            if parsed:
                published = pick(published, parsed)
                break

        # Class/id heuristics
        class_keywords = ('date', 'time', 'publish', 'posted', 'update', 'modified')
        for elem in soup.find_all(True, class_=True):
            class_str = ' '.join(elem.get('class', [])).lower()
            if any(k in class_str for k in class_keywords):
                parsed = self.parse_date_string(elem.get('content') or elem.get('datetime') or elem.text)
                if parsed:
                    if not published:
                        published = parsed
                    elif not updated and parsed != published:
                        updated = parsed
                    break

        return {
            'published_at': published,
            'updated_at': updated
        }

    async def extract_page_data(self, url: str, crawler: AsyncWebCrawler, page_number: int,
                                head_headers: Optional[Dict[str, str]] = None,
                                head_status: Optional[int] = None,
                                depth: int = 0,
                                source_type: str = "seed") -> Optional[Dict]:
        """Extract data from a single page"""
        await self.rate_limiter.acquire()

        try:
            run_config = CrawlerRunConfig(
                word_count_threshold=0,  # No threshold - capture all content
                exclude_external_links=False,
                process_iframes=False,  # Disable to avoid issues
                remove_overlay_elements=False,  # Don't remove any elements
                cache_mode=CacheMode.BYPASS,
                # Wait for JavaScript to render content - increased delays for heavy JS sites
                wait_until="networkidle",  # Wait until network is idle
                page_timeout=90000,  # 90 second timeout
                delay_before_return_html=5.0  # Wait 5 seconds after page load
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


            # Check if markdown is being extracted, use html2text then BeautifulSoup as fallbacks
            if not result.markdown or len(result.markdown.strip()) <= 1:
                # Try html2text first
                h = html2text.HTML2Text()
                h.ignore_links = False
                h.body_width = 0
                h.ignore_images = False
                markdown_content = h.handle(result.html)

                # If html2text also fails, use BeautifulSoup to extract text
                if not markdown_content or len(markdown_content.strip()) <= 1:
                    print(f"Warning: html2text failed, using BeautifulSoup text extraction for {url}")

                    # Try fit_html first (contains filtered content), fallback to cleaned_html, then html
                    html_to_parse = result.fit_html if hasattr(result, 'fit_html') and result.fit_html else \
                                  result.cleaned_html if hasattr(result, 'cleaned_html') and result.cleaned_html else \
                                  result.html
                    soup_temp = BeautifulSoup(html_to_parse, 'html.parser')

                    # Try to find main content area first
                    main_content = soup_temp.find('main') or soup_temp.find('article') or soup_temp.find('body')
                    if main_content:
                        # Extract text with proper formatting
                        # Remove script and style elements
                        for script in main_content(['script', 'style', 'nav', 'header', 'footer']):
                            script.decompose()

                        # Get text with newlines preserved
                        markdown_content = main_content.get_text(separator='\n', strip=True)

                        # Clean up extra newlines
                        lines = [line.strip() for line in markdown_content.split('\n') if line.strip()]
                        markdown_content = '\n\n'.join(lines)
                else:
                    print(f"Info: Using html2text fallback for {url}")
            else:
                markdown_content = result.markdown

            # Parse HTML for additional data
            soup = BeautifulSoup(result.html, 'html.parser')

            # Extract title
            title = []
            title_tag = soup.find('title')
            if title_tag:
                title.append(title_tag.text.strip())

            # Canonical URL
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

            # Extract date if selector provided plus smart extraction
            dates = []
            if self.config.date_selector:
                date_elements = soup.select(self.config.date_selector)
                for elem in date_elements:
                    date_text = elem.get('content') or elem.get('datetime') or elem.text
                    if date_text:
                        normalized = self.parse_date_string(date_text)
                        if normalized:
                            dates.append(normalized)
                        else:
                            dates.append(date_text.strip())

            date_info = self.extract_dates(result.html, soup)
            if date_info.get('published_at'):
                dates.insert(0, date_info['published_at'])
            if date_info.get('updated_at') and date_info['updated_at'] not in dates:
                dates.append(date_info['updated_at'])

            lang = self.detect_language(result.html, head_headers)

            # Extract images - use both crawl4ai and BeautifulSoup
            images = []
            if not self.config.skip_images:
                image_exceptions = []
                if self.config.image_exceptions:
                    image_exceptions = [s.strip() for s in self.config.image_exceptions.split(',')]

                # First try crawl4ai's media extraction
                for img in result.media.get('images', []):
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

                # If crawl4ai found no images, fallback to BeautifulSoup
                if len(images) == 0:
                    print(f"Info: No images from crawl4ai, using BeautifulSoup fallback for {url}")
                    img_tags = soup.find_all('img')
                    for img_tag in img_tags:
                        img_src = img_tag.get('src') or img_tag.get('data-src') or img_tag.get('data-lazy-src')
                        if img_src and img_src.startswith(('http', '/', 'data:')):
                            should_exclude = False
                            if image_exceptions:
                                for exception in image_exceptions:
                                    if img_tag.find_parent(exception):
                                        should_exclude = True
                                        break

                            if not should_exclude and not img_src.startswith('data:'):
                                absolute_img_url = urljoin(url, img_src)
                                if not urlparse(absolute_img_url).path.lower().endswith("piwik.php") and absolute_img_url not in images:
                                    images.append(absolute_img_url)

            # Download images to page-specific directory
            downloaded_images = []
            if images and not self.config.skip_images:
                # Create page directory and images subfolder
                page_dir = await self.create_page_directory(page_number)
                images_dir = page_dir / "images"

                async with aiohttp.ClientSession(headers=self.headers) as session:
                    for img_url in images:
                        filename = await self.download_image(img_url, session, images_dir)
                        if filename:
                            downloaded_images.append(filename)

            # Content hash for freshness detection
            content_for_hash = markdown_content if markdown_content else result.html
            content_hash = hashlib.sha256(content_for_hash.encode('utf-8', errors='ignore')).hexdigest()

            fetch_time = datetime.now().isoformat()
            content_length = (head_headers or {}).get('content-length') if head_headers else None
            sitemap_lastmod = self.sitemap_lastmod.get(url)
            domain = urlparse(final_url).netloc if final_url else urlparse(url).netloc
            canonicalized_path = urlparse(final_url).path if final_url else urlparse(url).path

            page_data = {
                'title': title,
                'page_url': [url],
                'final_url': final_url,
                'canonical_url': canonical_url,
                'domain': domain,
                'canonicalized_path': canonicalized_path,
                'meta_img_url': meta_img_url,
                'images': downloaded_images if not self.config.skip_images else images,
                'date': dates,
                'lang': lang,
                'source_type': source_type,
                'crawl_depth': depth,
                'published_at': date_info.get('published_at'),
                'updated_at': date_info.get('updated_at'),
                'last_modified_header': (head_headers or {}).get('last-modified') if head_headers else None,
                'etag': (head_headers or {}).get('etag') if head_headers else None,
                'http_status': head_status,
                'content_length': content_length,
                'fetch_time': fetch_time,
                'sitemap_lastmod': sitemap_lastmod,
                'redirect_chain': [url, final_url] if final_url and final_url != url else [url],
                'content_hash': content_hash
            }

            return {
                'data': page_data,
                'markdown': markdown_content,
                'html_content': result.html
            }

        except Exception as e:
            print(f"Error extracting data from {url}: {e}")
            return None

    async def save_page_data(self, page_data: Dict, page_number: int):
        """Save page data to JSON and markdown files in page-specific directory"""
        # Create page directory
        page_dir = await self.create_page_directory(page_number)

        if self.storage_manager:
            # Use storage_manager for consistent file operations
            await self.storage_manager.save_page_json(page_number, page_data['data'])
            await self.storage_manager.save_page_content(page_number, page_data['markdown'] if page_data['markdown'] else "")
        else:
            # Original logic for backwards compatibility
            # Save JSON data
            json_filename = page_dir / f"data_{page_number:05d}.json"
            async with aiofiles.open(json_filename, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(page_data['data'], indent=2, ensure_ascii=False))

            # Save markdown content
            md_filename = page_dir / f"content_{page_number:05d}.md"
            async with aiofiles.open(md_filename, 'w', encoding='utf-8') as f:
                await f.write(page_data['markdown'] if page_data['markdown'] else "")

    async def crawl_page(self, url: str, crawler: AsyncWebCrawler):
        """Crawl a single page"""
        async with self.semaphore:
            # Check if URL already visited or max pages reached
            async with self.counter_lock:
                if url in self.visited_urls or (self.config.max_pages > 0 and self.page_counter >= self.config.max_pages):
                    return

                self.visited_urls.add(url)
                self.page_counter += 1
                current_page_number = self.page_counter

            # Display progress
            total_pages = self.config.max_pages if self.config.max_pages > 0 else "unlimited"
            if self.config.max_pages > 0:
                print(f"Crawling [{current_page_number}/{self.config.max_pages}]: {url}")
            else:
                print(f"Crawling [{current_page_number}/unlimited]: {url}")

            # Update tracking systems
            if self.url_tracking_manager:
                await self.url_tracking_manager.set_processing(url, current_page_number)
            if self.progress_tracker:
                await self.progress_tracker.set_current_url(url)
            if self.job_state_manager:
                await self.job_state_manager.set_current_url(url)

            head_status, head_headers = await self.fetch_head(url)

            # Handle direct PDF URLs
            page_data = None
            if await self.is_pdf_resource(url, head_status, head_headers):
                pdf_entry = await self.fetch_and_save_pdf(url, current_page_number)
                if pdf_entry:
                    pdf_lang = self.detect_language(None, head_headers)
                    page_data = {
                        'data': {
                            'title': [],
                            'page_url': [url],
                            'meta_img_url': [],
                            'images': [],
                            'date': [],
                            'lang': pdf_lang,
                            'source_type': self.url_source.get(url, 'seed'),
                            'crawl_depth': self.url_depth.get(url, 0),
                            'pdfs': [pdf_entry]
                        },
                        'markdown': '',
                        'html_content': ''
                    }
            else:
                # Extract page data
                page_data = await self.extract_page_data(
                    url,
                    crawler,
                    current_page_number,
                    head_headers=head_headers,
                    head_status=head_status,
                    depth=self.url_depth.get(url, 0),
                    source_type=self.url_source.get(url, 'seed')
                )

            if page_data:
                pdf_entries = page_data['data'].get('pdfs', [])

                # Detect and download PDF links in HTML content
                if page_data.get('html_content'):
                    pdf_links = self.extract_pdf_links(page_data['html_content'], url)
                    if pdf_links:
                        async with aiohttp.ClientSession(headers=self.headers) as pdf_session:
                            for pdf_url in pdf_links:
                                pdf_entry = await self.fetch_and_save_pdf(pdf_url, current_page_number, session=pdf_session)
                                if pdf_entry:
                                    pdf_entries.append(pdf_entry)

                page_data['data']['pdfs'] = pdf_entries

                await self.save_page_data(page_data, current_page_number)

                # Extract header dates for URLTrackingManager
                header_dates = None
                if head_headers:
                    header_dates = {
                        "last_modified": head_headers.get('last-modified'),
                        "date": head_headers.get('date')
                    }

                # Update tracking systems with completion
                if self.url_tracking_manager:
                    await self.url_tracking_manager.set_completed(url, header_dates)
                if self.progress_tracker:
                    await self.progress_tracker.increment_completed()
                    if len(pdf_entries) > 0:
                        await self.progress_tracker.increment_pdfs(len(pdf_entries))
                    if not self.config.skip_images and page_data['data'].get('images'):
                        await self.progress_tracker.increment_images(len(page_data['data']['images']))
                if self.job_state_manager:
                    await self.job_state_manager.increment_completed()

                # Discover new URLs if in discovery mode
                if self.config.discovery_mode:
                    new_urls = await self.discover_urls(page_data['html_content'], url)
                    for new_url in new_urls:
                        if urlparse(new_url).path.lower().endswith("piwik.php"):
                            continue
                        if new_url not in self.visited_urls and new_url not in self.to_visit:
                            self.to_visit.append(new_url)
                            self.url_depth[new_url] = self.url_depth.get(url, 0) + 1
                            self.url_source[new_url] = "discovery"

                            # Add to URLTrackingManager if available
                            if self.url_tracking_manager:
                                await self.url_tracking_manager.add_url(new_url, source="discovery")
            else:
                # URL extraction failed
                error_msg = "Extraction failed"

                # Update tracking systems with failure
                if self.url_tracking_manager:
                    await self.url_tracking_manager.set_failed(url, error_msg)
                if self.progress_tracker:
                    await self.progress_tracker.increment_failed()
                    await self.progress_tracker.increment_errors()
                if self.job_state_manager:
                    await self.job_state_manager.increment_failed()

                # Decrement if extraction failed
                async with self.counter_lock:
                    self.page_counter -= 1

    async def crawl(self) -> Dict:
        """Main crawl method"""
        try:
            await self.setup_directories()

            # Initialize tracking systems
            if self.url_tracking_manager:
                await self.url_tracking_manager.initialize()
            if self.progress_tracker:
                await self.progress_tracker.start()

            # Update state: Job is now running
            if self.job_state_manager:
                await self.job_state_manager.set_status("running")

            # Emit stage: initialization
            if self.progress_tracker:
                await self.progress_tracker.set_stage("initialization")

            start_url = str(self.config.url)

            # Check if URL is a sitemap
            if await self.is_sitemap(start_url):
                print(f"Detected sitemap: {start_url}")
                urls = await self.parse_sitemap(start_url)

                # Event: Sitemap detected
                if self.event_emitter:
                    await self.event_emitter.sitemap_detected(start_url, len(urls))

                urls_to_crawl = urls[:self.config.max_pages] if self.config.max_pages > 0 else urls
                self.to_visit = urls_to_crawl
                for u in self.to_visit:
                    self.url_depth[u] = 0
                    self.url_source[u] = "sitemap"
                print(f"Found {len(urls)} URLs in sitemap, will crawl {len(self.to_visit)}")

                # Event: URLs discovered
                if self.event_emitter:
                    await self.event_emitter.urls_discovered(len(urls), len(self.to_visit))
                if self.job_state_manager:
                    await self.job_state_manager.set_total_urls(len(self.to_visit))
                if self.progress_tracker:
                    await self.progress_tracker.set_total_urls(len(self.to_visit))
            else:
                self.to_visit = [start_url]
                self.url_depth[start_url] = 0
                self.url_source[start_url] = "seed"

                # Add seed URL to tracking
                if self.url_tracking_manager:
                    await self.url_tracking_manager.add_url(start_url, source="seed")
                if self.job_state_manager:
                    await self.job_state_manager.set_total_urls(1)
                if self.progress_tracker:
                    await self.progress_tracker.set_total_urls(1)

            # Event: Crawling started
            total_to_crawl = len(self.to_visit) if not self.config.discovery_mode else self.config.max_pages
            if self.event_emitter:
                await self.event_emitter.crawling_started(total_to_crawl if total_to_crawl > 0 else 0)

            # Emit stage: scraping
            if self.progress_tracker:
                await self.progress_tracker.set_stage("scraping")

            browser_config = BrowserConfig(
                headless=True,
                verbose=False
            )

            async with AsyncWebCrawler(config=browser_config) as crawler:
                # Continue while there are URLs to visit and we haven't reached max_pages (or max_pages is 0)
                while self.to_visit and (self.config.max_pages == 0 or self.page_counter < self.config.max_pages):
                    # Process batch of URLs
                    batch_size = min(self.config.max_concurrency, len(self.to_visit))
                    batch = self.to_visit[:batch_size]
                    self.to_visit = self.to_visit[batch_size:]

                    tasks = [self.crawl_page(url, crawler) for url in batch]
                    await asyncio.gather(*tasks, return_exceptions=True)

            # Job completed successfully
            if self.progress_tracker:
                await self.progress_tracker.set_stage("completed")
                await self.progress_tracker.stop()

                # Generate and save summary
                summary_data = await self.progress_tracker.get_summary()
                if self.summary_manager:
                    formatted_summary = SummaryManager.format_summary(
                        job_id=self.job_id,
                        stage="completed",
                        progress=summary_data,
                        output_directory=str(self.output_dir),
                        error=None
                    )
                    await self.summary_manager.save_summary(formatted_summary)

                    # Emit summary event
                    if self.event_emitter:
                        await self.event_emitter.job_summary(formatted_summary)

                    # Print text summary
                    print("\n" + SummaryManager.format_text_summary(formatted_summary))

            # Legacy event for backwards compatibility
            if self.event_emitter:
                await self.event_emitter.job_completed(
                    self.page_counter,
                    str(self.output_dir),
                    success=True
                )
            if self.job_state_manager:
                await self.job_state_manager.set_status("completed")

            return {
                'pages_crawled': self.page_counter,
                'output_directory': str(self.output_dir),
                'label': self.config.label
            }

        except Exception as e:
            # Job failed
            error_msg = str(e)
            print(f"Crawl job failed: {error_msg}")

            if self.progress_tracker:
                await self.progress_tracker.set_stage("failed")
                await self.progress_tracker.stop()

                # Generate and save summary for failed job
                summary_data = await self.progress_tracker.get_summary()
                if self.summary_manager:
                    formatted_summary = SummaryManager.format_summary(
                        job_id=self.job_id,
                        stage="failed",
                        progress=summary_data,
                        output_directory=str(self.output_dir),
                        error=error_msg
                    )
                    await self.summary_manager.save_summary(formatted_summary)

                    # Emit summary event
                    if self.event_emitter:
                        await self.event_emitter.job_summary(formatted_summary)

                    # Print text summary
                    print("\n" + SummaryManager.format_text_summary(formatted_summary))

            # Legacy event for backwards compatibility
            if self.event_emitter:
                await self.event_emitter.job_completed(
                    self.page_counter,
                    str(self.output_dir),
                    success=False,
                    error=error_msg
                )
            if self.job_state_manager:
                await self.job_state_manager.set_error(error_msg)

            raise

import asyncio
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List, Set, Dict, Optional, Any
from urllib.parse import urljoin, urlparse, urlunparse
from bs4 import BeautifulSoup
import aiohttp
import aiofiles
import html2text
from crawl4ai import AsyncWebCrawler
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig, CacheMode

from models import CrawlConfig


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

    async def create_page_directory(self, page_number: int) -> Path:
        """Create directory for a specific page"""
        if self.storage_manager:
            return self.storage_manager.create_page_directory(
                page_number,
                create_images_dir=not self.config.skip_images
            )
        else:
            # Original logic for backwards compatibility
            page_dir = self.output_dir / f"page_{page_number:05d}"
            page_dir.mkdir(exist_ok=True)

            if not self.config.skip_images:
                images_dir = page_dir / "images"
                images_dir.mkdir(exist_ok=True)

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
                            urls.append(loc.text)
        except Exception as e:
            print(f"Error parsing sitemap {sitemap_url}: {e}")

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
                urls.append(normalized)

        return urls

    async def download_image(self, image_url: str, session: aiohttp.ClientSession, images_dir: Path) -> Optional[str]:
        """Download image and return local filename"""
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

    async def extract_page_data(self, url: str, crawler: AsyncWebCrawler, page_number: int) -> Optional[Dict]:
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

            if not result.success:
                print(f"Failed to crawl {url}: {result.error_message}")
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

            # Extract meta image
            meta_img_url = []
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                meta_img_url.append(og_image['content'])

            # Extract date if selector provided
            dates = []
            if self.config.date_selector:
                date_elements = soup.select(self.config.date_selector)
                for elem in date_elements:
                    date_text = elem.get('content') or elem.get('datetime') or elem.text
                    if date_text:
                        dates.append(date_text.strip())

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
                                if absolute_img_url not in images:
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

            page_data = {
                'title': title,
                'page_url': [url],
                'meta_img_url': meta_img_url,
                'images': downloaded_images if not self.config.skip_images else images,
                'date': dates
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
            json_filename = page_dir / "data.json"
            async with aiofiles.open(json_filename, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(page_data['data'], indent=2, ensure_ascii=False))

            # Save markdown content
            md_filename = page_dir / "content.md"
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

            # Event: Starting to fetch URL
            if self.event_emitter:
                await self.event_emitter.url_fetching(url, current_page_number, self.config.max_pages)
            if self.job_state_manager:
                await self.job_state_manager.set_current_url(url)

            # Extract page data
            page_data = await self.extract_page_data(url, crawler, current_page_number)

            if page_data:
                # Event: URL scraped successfully
                if self.event_emitter:
                    await self.event_emitter.url_scraped(url, current_page_number, success=True)

                await self.save_page_data(page_data, current_page_number)

                # Event: URL processing completed
                files_created = [
                    f"page_{current_page_number:05d}/data.json",
                    f"page_{current_page_number:05d}/content.md"
                ]
                if self.event_emitter:
                    await self.event_emitter.url_completed(url, current_page_number, files_created)
                if self.job_state_manager:
                    await self.job_state_manager.increment_completed()

                # Discover new URLs if in discovery mode
                if self.config.discovery_mode:
                    new_urls = await self.discover_urls(page_data['html_content'], url)
                    for new_url in new_urls:
                        if new_url not in self.visited_urls and new_url not in self.to_visit:
                            self.to_visit.append(new_url)
            else:
                # Event: URL scraping failed
                if self.event_emitter:
                    await self.event_emitter.url_scraped(url, current_page_number, success=False, error="Extraction failed")
                if self.job_state_manager:
                    await self.job_state_manager.increment_failed()

                # Decrement if extraction failed
                async with self.counter_lock:
                    self.page_counter -= 1

    async def crawl(self) -> Dict:
        """Main crawl method"""
        try:
            await self.setup_directories()

            # Update state: Job is now running
            if self.job_state_manager:
                await self.job_state_manager.set_status("running")

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
                print(f"Found {len(urls)} URLs in sitemap, will crawl {len(self.to_visit)}")

                # Event: URLs discovered
                if self.event_emitter:
                    await self.event_emitter.urls_discovered(len(urls), len(self.to_visit))
                if self.job_state_manager:
                    await self.job_state_manager.set_total_urls(len(self.to_visit))
            else:
                self.to_visit = [start_url]
                if self.job_state_manager:
                    await self.job_state_manager.set_total_urls(1)

            # Event: Crawling started
            total_to_crawl = len(self.to_visit) if not self.config.discovery_mode else self.config.max_pages
            if self.event_emitter:
                await self.event_emitter.crawling_started(total_to_crawl if total_to_crawl > 0 else 0)

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

            # Event: Job completed successfully
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
            # Event: Job failed
            error_msg = str(e)
            print(f"Crawl job failed: {error_msg}")

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

import asyncio
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List, Set, Dict, Optional
from urllib.parse import urljoin, urlparse, urlunparse
from bs4 import BeautifulSoup
import aiohttp
import aiofiles
from crawl4ai import AsyncWebCrawler
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig, CacheMode

from models import CrawlConfig, PageData


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

    def __init__(self, config: CrawlConfig):
        self.config = config
        self.visited_urls: Set[str] = set()
        self.to_visit: List[str] = []
        self.pages_data: List[Dict] = []
        self.rate_limiter = RateLimiter(config.max_rpm, config.request_delay)
        self.semaphore = asyncio.Semaphore(config.max_concurrency)
        self.page_counter = 0

        # Generate label if not provided
        if not config.label:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            domain = urlparse(str(config.url)).netloc.replace(".", "_")
            self.config.label = f"{domain}_{timestamp}"

        # Setup output directory
        self.output_dir = Path(config.output_dir) / self.config.label
        self.images_dir = self.output_dir / "images"

    async def setup_directories(self):
        """Create necessary directories"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if not self.config.skip_images:
            self.images_dir.mkdir(exist_ok=True)

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
            async with aiohttp.ClientSession() as session:
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
            async with aiohttp.ClientSession() as session:
                async with session.get(sitemap_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
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

    async def download_image(self, image_url: str, session: aiohttp.ClientSession) -> Optional[str]:
        """Download image and return local filename"""
        try:
            async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    # Generate filename from URL
                    parsed = urlparse(image_url)
                    filename = os.path.basename(parsed.path)
                    if not filename or '.' not in filename:
                        filename = f"image_{abs(hash(image_url))}.jpg"

                    # Sanitize filename
                    filename = re.sub(r'[^\w\-_\.]', '_', filename)
                    filepath = self.images_dir / filename

                    # Save image
                    content = await response.read()
                    async with aiofiles.open(filepath, 'wb') as f:
                        await f.write(content)

                    return filename
        except Exception as e:
            print(f"Error downloading image {image_url}: {e}")

        return None

    async def extract_page_data(self, url: str, crawler: AsyncWebCrawler) -> Optional[Dict]:
        """Extract data from a single page"""
        await self.rate_limiter.acquire()

        try:
            run_config = CrawlerRunConfig(
                word_count_threshold=10,
                exclude_external_links=False,
                process_iframes=True,
                remove_overlay_elements=True,
                cache_mode=CacheMode.BYPASS
            )

            result = await crawler.arun(url=url, config=run_config)

            if not result.success:
                print(f"Failed to crawl {url}: {result.error_message}")
                return None

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

            # Extract images
            images = []
            if not self.config.skip_images:
                image_exceptions = []
                if self.config.image_exceptions:
                    image_exceptions = [s.strip() for s in self.config.image_exceptions.split(',')]

                for img in result.media.get('images', []):
                    img_src = img.get('src', '')
                    if img_src:
                        # Check if image should be excluded
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

            # Download images
            downloaded_images = []
            if images and not self.config.skip_images:
                async with aiohttp.ClientSession() as session:
                    for img_url in images:
                        filename = await self.download_image(img_url, session)
                        if filename:
                            downloaded_images.append(img_url)

            page_data = {
                'title': title,
                'page_url': [url],
                'meta_img_url': meta_img_url,
                'images': downloaded_images if not self.config.skip_images else images,
                'date': dates
            }

            return {
                'data': page_data,
                'markdown': result.markdown,
                'html_content': result.html
            }

        except Exception as e:
            print(f"Error extracting data from {url}: {e}")
            return None

    async def save_page_data(self, page_data: Dict, page_number: int):
        """Save page data to JSON and markdown files"""
        # Save JSON data
        json_filename = self.output_dir / f"data_{page_number:05d}.json"
        async with aiofiles.open(json_filename, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(page_data['data'], indent=2, ensure_ascii=False))

        # Save markdown content
        md_filename = self.output_dir / f"site_{page_number:05d}.md"
        async with aiofiles.open(md_filename, 'w', encoding='utf-8') as f:
            await f.write(page_data['markdown'])

    async def crawl_page(self, url: str, crawler: AsyncWebCrawler):
        """Crawl a single page"""
        async with self.semaphore:
            if url in self.visited_urls or self.page_counter >= self.config.max_pages:
                return

            self.visited_urls.add(url)
            print(f"Crawling [{self.page_counter + 1}/{self.config.max_pages}]: {url}")

            page_data = await self.extract_page_data(url, crawler)

            if page_data:
                self.page_counter += 1
                await self.save_page_data(page_data, self.page_counter)

                # Discover new URLs if in discovery mode
                if self.config.discovery_mode:
                    new_urls = await self.discover_urls(page_data['html_content'], url)
                    for new_url in new_urls:
                        if new_url not in self.visited_urls and new_url not in self.to_visit:
                            self.to_visit.append(new_url)

    async def crawl(self) -> Dict:
        """Main crawl method"""
        await self.setup_directories()

        start_url = str(self.config.url)

        # Check if URL is a sitemap
        if await self.is_sitemap(start_url):
            print(f"Detected sitemap: {start_url}")
            urls = await self.parse_sitemap(start_url)
            self.to_visit = urls[:self.config.max_pages]
            print(f"Found {len(urls)} URLs in sitemap, will crawl {len(self.to_visit)}")
        else:
            self.to_visit = [start_url]

        browser_config = BrowserConfig(
            headless=True,
            verbose=False
        )

        async with AsyncWebCrawler(config=browser_config) as crawler:
            while self.to_visit and self.page_counter < self.config.max_pages:
                # Process batch of URLs
                batch_size = min(self.config.max_concurrency, len(self.to_visit))
                batch = self.to_visit[:batch_size]
                self.to_visit = self.to_visit[batch_size:]

                tasks = [self.crawl_page(url, crawler) for url in batch]
                await asyncio.gather(*tasks, return_exceptions=True)

        return {
            'pages_crawled': self.page_counter,
            'output_directory': str(self.output_dir),
            'label': self.config.label
        }

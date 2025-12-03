import asyncio
import json
import os
import hashlib
import time
import re
from datetime import datetime
from pathlib import Path
from typing import List, Set, Dict, Optional, Any, Tuple
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
from services.url_tracking_manager import URLTrackingManager, generate_url_hash
from services.summary_manager import SummaryManager


def clean_html_for_markdown(html: str) -> str:
    """
    Clean raw HTML to retain only meaningful page content before markdown conversion.
    """
    soup = BeautifulSoup(html, "html.parser")
    # MAIN CONTENT ONLY REGION
    main_candidates = []
    main_candidates.extend(soup.find_all("main"))
    id_targets = {"main", "main-content", "content", "main-content-anchor"}
    main_candidates.extend(
        soup.find_all(lambda tag: tag.get("id") and str(tag.get("id")).lower() in id_targets)
    )
    main_candidates.extend(
        soup.find_all(lambda tag: tag.get("role") and str(tag.get("role")).lower() == "main")
    )
    if main_candidates:
        soup = BeautifulSoup(str(main_candidates[0]), "html.parser")
    # JUNK Tags removal + substrings like nav, menu, header etc
    for tag in soup.find_all(["header", "footer", "nav", "aside", "form", "script", "style", "noscript"]):
        tag.decompose()
    substrings = [
        "nav", "menu", "breadcrumb", "sidebar", "cookie", "consent", "cookie-banner",
        "footer", "header", "topbar", "toolbar", "hero-stage", "stage",
        "social", "share", "tracking", "banner", "popup"
    ]
    def has_bad_attr(tag):
        for attr in ("id", "class"):
            val = tag.get(attr)
            if not val:
                continue
            values = val if isinstance(val, list) else [val]
            for v in values:
                text_v = str(v).lower()
                if any(sub in text_v for sub in substrings):
                    return True
        return False

    for t in list(soup.find_all(has_bad_attr)):
        t.decompose()
    ################################################################################### HAWK WEBSITE REGION ##################################################################
    # HAWK-specific content removal (sitewide navigation, cookie, social, and footer blocks)
    navigation_keywords = [
        "hauptnavigation", "hauptmenü", "schnellzugriff",
        "diese seite teilen", "cookie-einstellungen", "ihre cookie-einstellungen",
        "technisch notwendig", "statistik", "externe medien", "sonstiges", "alle akzeptieren", "ablehnen",
        "impressum", "datenschutzerklärung", "datenschutzhinweis", "barrierefreiheit", "mittelverwendung",
        "meldestelle hinweisgeberschutzgesetz", "korruptionsprävention", "studienorganisation",
        "facebook", "linkedin", "pinterest", "xing", "whatsapp"
    ]

    def is_global_nav(tag):
        if tag.name not in ("section", "div"):
            return False
        text = (tag.get_text(" ", strip=True) or "").lower()
        return any(k in text for k in navigation_keywords)
    for t in list(soup.find_all(is_global_nav)):
        t.decompose()
    return str(soup)

def filter_markdown_lines(markdown: str) -> str:
    """Remove leftover navigation/cookie/share lines after markdown conversion."""
    drop_phrases = [
        "hauptnavigation", "hauptmenü", "schnellzugriff",
        "cookie-einstellungen", "ihre cookie-einstellungen",
        "technisch notwendig", "statistik", "externe medien", "sonstiges",
        "bei facebook teilen", "bei linkedin teilen", "bei pinterest teilen",
        "bei xing teilen", "bei whatsapp teilen", "diese seite teilen"
    ]
    kept = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if any(p in lower for p in drop_phrases):
            continue
        kept.append(line)
    return "\n".join(kept)
               

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

        # Preload sitemap metadata for fast language/date lookups (constant-time via dict)
        self.hawk_sitemap_path = os.getenv("HAWK_SITEMAP_JSON", "data/sitemap.json")
        self.hawk_sitemap_map = self._load_hawk_sitemap_map(self.hawk_sitemap_path)

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

    @staticmethod
    def _normalize_url_key(url: str) -> Optional[str]:
        """Create a normalized key for quick sitemap map lookup."""
        if not url:
            return None
        try:
            parsed = urlparse(url)
            path = parsed.path.rstrip('/') or '/'
            return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, '', '', ''))
        except Exception:
            return None

    def _load_hawk_sitemap_map(self, path: str) -> Dict[str, Dict[str, str]]:
        """Load sitemap JSON into a normalized dict; silent fallback to empty."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {}
            mapped = {}
            for raw_url, meta in data.items():
                key = self._normalize_url_key(raw_url)
                if key:
                    mapped[key] = meta if isinstance(meta, dict) else {}
            return mapped
        except Exception:
            return {}

    def _lookup_sitemap_entry(self, url: str) -> Optional[Dict[str, str]]:
        key = self._normalize_url_key(url)
        if not key:
            return None
        return self.hawk_sitemap_map.get(key)

    def _first_sitemap_entry(self, *urls: str) -> Optional[Dict[str, str]]:
        """Return the first sitemap entry found for the provided URLs."""
        for u in urls:
            if not u:
                continue
            entry = self._lookup_sitemap_entry(u)
            if entry:
                return entry
        return None

    @staticmethod
    def _parse_http_date(date_str: Optional[str]) -> Optional[str]:
        """Parse HTTP date string to ISO format with timezone if possible."""
        if not date_str:
            return None
        try:
            dt = parsedate_to_datetime(date_str)
            if dt:
                # Ensure timezone-aware; parsedate_to_datetime returns aware for HTTP dates
                return dt.isoformat()
        except Exception:
            return None
        return None

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
        urls_with_dates = []  # List of (url, date) tuples to preserve duplicates for URLTrackingManager

        try:
            # Create session with increased max response size for large sitemaps
            connector = aiohttp.TCPConnector(limit=100)
            async with aiohttp.ClientSession(headers=self.headers, connector=connector) as session:
                async with session.get(sitemap_url, timeout=aiohttp.ClientTimeout(total=30),
                                       max_line_size=16*1024, max_field_size=16*1024) as response:
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

                            # Store for URLTrackingManager (as tuple to preserve duplicates)
                            urls_with_dates.append((url, lastmod_date))

                    # Fallback: Parse as plain text list if no XML URLs were found
                    if not urls:
                        print(f"No URLs found via XML parsing, trying plain text fallback for {sitemap_url}")
                        # Split content by newlines and extract valid URLs
                        lines = content.strip().split('\n')
                        url_pattern = re.compile(r'^https?://[^\s]+$')
                        for line in lines:
                            line = line.strip()
                            # Check if line matches URL pattern
                            if url_pattern.match(line):
                                # Skip piwik.php tracking pixels
                                if urlparse(line).path.lower().endswith("piwik.php"):
                                    continue
                                urls.append(line)
                                urls_with_dates.append((line, None))  # Preserve duplicates

                        if urls:
                            print(f"Found {len(urls)} URLs via plain text parsing")

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

    async def fetch_head(self, url: str) -> Tuple[Optional[int], Dict[str, str]]:
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

    async def fetch_and_save_pdf(self, pdf_url: str, page_number: int, session: Optional[aiohttp.ClientSession] = None, url_hash: Optional[str] = None) -> Optional[Dict[str, str]]:
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

                # Use hash-based or page number-based storage
                if url_hash and self.storage_manager:
                    # Hash-based storage
                    self.storage_manager.create_hash_directory(url_hash, create_files_dir=True)
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

    def detect_language(
        self,
        html_content: Optional[str],
        head_headers: Optional[Dict[str, str]],
        url: Optional[str] = None,
        sitemap_entry: Optional[Dict[str, str]] = None
    ) -> Optional[str]:
        """
        Prefer sitemap JSON language when available; fallback to headers/HTML lang.
        Returns an uppercased language code when found.
        """
        entry = sitemap_entry or (self._lookup_sitemap_entry(url) if url else None)
        if entry and entry.get("language"):
            return entry["language"].upper()

        if head_headers:
            content_lang = head_headers.get('content-language')
            if content_lang:
                lang_val = content_lang.split(',')[0].split(';')[0].strip().lower()
                if lang_val:
                    return lang_val.upper()

        if html_content:
            soup = BeautifulSoup(html_content, 'html.parser')
            html_tag = soup.find('html')
            if html_tag and html_tag.get('lang'):
                lang_val = html_tag.get('lang').split('-')[0].strip().lower()
                if lang_val:
                    return lang_val.upper()

            meta_lang = soup.find('meta', attrs={'http-equiv': 'Content-Language'})
            if meta_lang and meta_lang.get('content'):
                lang_val = meta_lang.get('content').split(',')[0].split(';')[0].strip().lower()
                if lang_val:
                    return lang_val.upper()

        return None

    async def extract_page_data(self, url: str, crawler: AsyncWebCrawler, page_number: int,
                                head_headers: Optional[Dict[str, str]] = None,
                                head_status: Optional[int] = None,
                                depth: int = 0,
                                source_type: str = "seed",
                                url_hash: Optional[str] = None) -> Optional[Dict]:
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


            cleaned_html = clean_html_for_markdown(result.html)

            # Convert cleaned HTML to markdown
            h = html2text.HTML2Text()
            h.ignore_links = False
            h.body_width = 0
            h.ignore_images = False
            markdown_content = h.handle(cleaned_html)

            # Fallback to text extraction if html2text yields nothing
            if not markdown_content or len(markdown_content.strip()) <= 1:
                print(f"Warning: html2text produced empty output, using BeautifulSoup text extraction for {url}")
                soup_temp = BeautifulSoup(cleaned_html, 'html.parser')
                main_content = soup_temp.find('body') or soup_temp
                text_content = main_content.get_text(separator='\n', strip=True)
                lines = [line.strip() for line in text_content.split('\n') if line.strip()]
                markdown_content = '\n\n'.join(lines)

            # Remove leftover navigation/cookie/share lines
            markdown_content = filter_markdown_lines(markdown_content)

            # Parse HTML for additional data
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

            # Extract meta image
            meta_img_url = []
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                meta_img_url.append(og_image['content'])

            final_url = getattr(result, 'final_url', None) or getattr(result, 'page_url', None)
            entry = self._first_sitemap_entry(url, final_url)

            lang = self.detect_language(result.html, head_headers, url=final_url or url, sitemap_entry=entry)
            updated_at = entry.get("last_modified") if entry else None
            if not entry and head_headers:
                updated_at = self._parse_http_date(head_headers.get("last-modified") or head_headers.get("date"))
                if updated_at and isinstance(updated_at, str) and " " in updated_at:
                    # If parsing failed to ISO, try datetime + isoformat fallback
                    try:
                        dt = parsedate_to_datetime(head_headers.get("last-modified") or head_headers.get("date"))
                        updated_at = dt.isoformat() if dt else updated_at
                    except Exception:
                        pass

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

            # Download images to hash-based directory
            downloaded_images = []
            if images and not self.config.skip_images:
                if url_hash and self.storage_manager:
                    # Use hash-based storage
                    self.storage_manager.create_hash_directory(url_hash, create_images_dir=True)
                    images_dir = self.storage_manager.get_hash_images_directory(url_hash)
                else:
                    # Fallback to page number-based storage
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
            content_length = len((result.html or "")) if result and result.html else None

            page_data = {
                'title': title,
                'page_url': [url],
                'url_hash': url_hash,
                'canonical_url': canonical_url,
                'meta_img_url': meta_img_url,
                'images': downloaded_images if not self.config.skip_images else images,
                'lang': lang,
                'updated_at': updated_at,
                'http_status': head_status,
                'content_length': content_length,
                'fetch_time': fetch_time,
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

    async def save_page_data(self, page_data: Dict, page_number: int, url_hash: Optional[str] = None):
        """Save page data to JSON and markdown files in hash-based directory"""
        if self.storage_manager and url_hash:
            # Use hash-based storage (new system)
            self.storage_manager.create_hash_directory(url_hash, create_images_dir=not self.config.skip_images)
            await self.storage_manager.save_hash_json(url_hash, page_data['data'])
            await self.storage_manager.save_hash_content(url_hash, page_data['markdown'] if page_data['markdown'] else "")
        elif self.storage_manager:
            # Use page number-based storage (deprecated)
            page_dir = await self.create_page_directory(page_number)
            await self.storage_manager.save_page_json(page_number, page_data['data'])
            await self.storage_manager.save_page_content(page_number, page_data['markdown'] if page_data['markdown'] else "")
        else:
            # Original logic for backwards compatibility (no storage_manager)
            page_dir = await self.create_page_directory(page_number)
            json_filename = page_dir / f"data_{page_number:05d}.json"
            async with aiofiles.open(json_filename, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(page_data['data'], indent=2, ensure_ascii=False))

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

            # Generate URL hash for storage
            url_hash = generate_url_hash(url)

            # Display progress
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
                pdf_entry = await self.fetch_and_save_pdf(url, current_page_number, url_hash=url_hash)
                if pdf_entry:
                    pdf_lang = self.detect_language(None, head_headers, url=url)
                    updated_at = (self._lookup_sitemap_entry(url) or {}).get("last_modified")
                    if not self._lookup_sitemap_entry(url) and head_headers:
                        updated_at = self._parse_http_date(head_headers.get("last-modified") or head_headers.get("date"))
                    page_data = {
                        'data': {
                            'title': [],
                            'page_url': [url],
                            'url_hash': url_hash,
                            'meta_img_url': [],
                            'images': [],
                            'lang': pdf_lang,
                            'updated_at': updated_at,
                            'source_type': self.url_source.get(url, 'seed'),
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
                    source_type=self.url_source.get(url, 'seed'),
                    url_hash=url_hash
                )

            if page_data:
                pdf_entries = page_data['data'].get('pdfs', [])

                # Detect and download PDF links in HTML content
                if page_data.get('html_content'):
                    pdf_links = self.extract_pdf_links(page_data['html_content'], url)
                    if pdf_links:
                        async with aiohttp.ClientSession(headers=self.headers) as pdf_session:
                            for pdf_url in pdf_links:
                                pdf_entry = await self.fetch_and_save_pdf(pdf_url, current_page_number, session=pdf_session, url_hash=url_hash)
                                if pdf_entry:
                                    pdf_entries.append(pdf_entry)

                page_data['data']['pdfs'] = pdf_entries

                await self.save_page_data(page_data, current_page_number, url_hash)

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

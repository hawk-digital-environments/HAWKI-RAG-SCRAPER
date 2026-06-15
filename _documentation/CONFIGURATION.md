# Configuration Guide

This guide covers advanced configuration options for the Crawl4AI FastAPI service, including environment variables, browser settings, performance tuning, and custom extractors.

## Table of Contents

- [Environment Variables](#environment-variables)
- [UI Configuration](#ui-configuration)
- [Crawl Configuration](#crawl-configuration)
- [Browser Configuration](#browser-configuration)
- [Rate Limiting Strategies](#rate-limiting-strategies)
- [Performance Tuning](#performance-tuning)
- [Custom Data Extractors](#custom-data-extractors)
- [Image Handling](#image-handling)
- [Output Configuration](#output-configuration)
- [Advanced Examples](#advanced-examples)

---

## Environment Variables

### Basic Configuration

Create a `.env` file in the project root:

```bash
# .env

# API Configuration
CRAWL4AI_API_TOKEN=your_secure_token_here
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=4

# Crawler Configuration
MAX_CONCURRENT_TASKS=5
DEFAULT_MAX_PAGES=100
DEFAULT_OUTPUT_DIR=output

# Logging
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FILE=crawler.log

# Browser Configuration
HEADLESS_BROWSER=true
BROWSER_VERBOSE=false

# Performance
REQUEST_TIMEOUT=30
PAGE_LOAD_TIMEOUT=60
```

### Loading Environment Variables

```python
# main.py
import os
from dotenv import load_dotenv

load_dotenv()

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))
API_WORKERS = int(os.getenv("API_WORKERS", "4"))
```

### Docker Environment Variables

```yaml
# docker-compose.yml
services:
  crawler:
    environment:
      - CRAWL4AI_API_TOKEN=${CRAWL4AI_API_TOKEN}
      - MAX_CONCURRENT_TASKS=5
      - LOG_LEVEL=INFO
      - HEADLESS_BROWSER=true
```

---

## UI Configuration

The SvelteKit UI lives in `ui/` and is started from the repository root with:

```bash
make start-ui
```

The Makefile target installs UI dependencies and starts the SvelteKit dev server:

```makefile
start-ui:
	npm install --prefix ui
	npm --prefix ui run dev
```

### UI Environment Variables

| Variable | Default | Used by | Description |
|----------|---------|---------|-------------|
| `PUBLIC_API_BASE_URL` | empty | `ui/src/lib/api/index.ts` | Optional browser-visible API base URL. Keep empty for same-origin `/api/...` during local development. |
| `CRAWLER_API_BASE_URL` | `http://localhost:8040`, fallback `http://localhost:8000` | `ui/src/lib/server/config.ts` | Crawler API base URL list. Comma-separated values are supported. |
| `RABBITMQ_MGMT_API_URL` | `http://localhost:15672/api` | `ui/src/lib/server/config.ts` | RabbitMQ management API base URL. |
| `RABBITMQ_MGMT_USER` | `guest` | `ui/src/lib/server/config.ts` | RabbitMQ management username. |
| `RABBITMQ_MGMT_PASSWORD` | `guest` | `ui/src/lib/server/config.ts` | RabbitMQ management password. |
| `PROFILES_HOST_DIR` | `../profiles` when running from `ui/` | `ui/src/routes/api/profiles/*` | Host directory where editable profile JSON files are read/written. |
| `PROFILES_CONTAINER_DIR` | `/var/www/html/profiles` | `ui/src/routes/api/profiles/*` | Container path sent in crawl submissions as `site_profile_path`. |

### UI API Flow

The browser UI calls `ui/src/lib/api/index.ts`. That client calls same-origin SvelteKit API routes by default:

```text
Browser page -> ui/src/lib/api/index.ts -> /api/... -> crawler/RabbitMQ/profile files
```

Do not import `ui/src/lib/api/stub.ts` from production routes. It is retained only as mock data for local experiments.

---

## Crawl Configuration

### Basic Parameters

```python
config = {
    "url": "https://example.com",
    "max_pages": 100,
    "output_dir": "output",
    "label": "my_project",
    "max_concurrency": 4,
    "max_rpm": 60
}
```

### Parameter Details

#### url (Required)
- **Type**: String (URL)
- **Description**: Starting URL for crawling
- **Validation**: Must be valid HTTP/HTTPS URL
- **Examples**:
  ```python
  "url": "https://example.com"
  "url": "https://example.com/sitemap.xml"
  "url": "https://example.com/blog"
  ```

#### max_pages (Optional)
- **Type**: Integer
- **Default**: 100
- **Range**: 1 to unlimited
- **Description**: Maximum number of pages to crawl
- **Use Cases**:
  - Small sites: 10-50
  - Medium sites: 100-500
  - Large sites: 1000+
- **Example**:
  ```python
  "max_pages": 50  # Limit to 50 pages
  ```

#### output_dir (Optional)
- **Type**: String
- **Default**: "output"
- **Description**: Base directory for storing crawled data
- **Note**: Actual output goes to `{output_dir}/{label}/`
- **Example**:
  ```python
  "output_dir": "/data/crawls"
  ```

#### label (Optional)
- **Type**: String or null
- **Default**: Auto-generated (`{domain}_{timestamp}`)
- **Description**: Label for this crawl job
- **Auto-generated Format**: `example_com_20250321_143022`
- **Example**:
  ```python
  "label": "blog_crawl_march_2025"
  ```

#### skip_images (Optional)
- **Type**: Boolean
- **Default**: false
- **Description**: Skip downloading images
- **Use When**:
  - Images not needed
  - Saving bandwidth
  - Faster crawling
- **Example**:
  ```python
  "skip_images": true
  ```

#### discovery_mode (Optional)
- **Type**: Boolean
- **Default**: false
- **Description**: Discover and crawl internal links
- **Use Cases**:
  - Explore entire website
  - Find all pages automatically
  - No sitemap available
- **Example**:
  ```python
  "discovery_mode": true
  ```

---

## Browser Configuration

### Default Configuration

The service uses Playwright with sensible defaults:

```python
# In crawler_service.py
browser_config = BrowserConfig(
    headless=True,
    verbose=False
)
```

### Custom Browser Configuration

Extend `CrawlerService` to customize browser settings:

```python
from crawl4ai.async_configs import BrowserConfig

# Custom configuration
browser_config = BrowserConfig(
    headless=True,
    verbose=False,
    browser_type="chromium",  # or "firefox", "webkit"
    user_agent="CustomBot/1.0",
    viewport={"width": 1920, "height": 1080},
    java_script_enabled=True,
    ignore_https_errors=False,
    extra_args=[
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage"
    ]
)
```

### Browser Types

#### Chromium (Default)
- **Pros**: Best compatibility, fastest
- **Cons**: Higher memory usage
- **Use For**: General web crawling

#### Firefox
- **Pros**: Better privacy features
- **Cons**: Slower than Chromium
- **Use For**: Sites that block Chromium

#### WebKit
- **Pros**: Lightweight
- **Cons**: Limited compatibility
- **Use For**: Mobile-first sites

### User Agent Configuration

```python
custom_user_agents = {
    "desktop": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "mobile": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)",
    "bot": "MyCrawler/1.0 (+https://example.com/crawler)"
}

browser_config = BrowserConfig(
    user_agent=custom_user_agents["bot"]
)
```

### Proxy Configuration

```python
browser_config = BrowserConfig(
    headless=True,
    proxy={
        "server": "http://proxy.example.com:8080",
        "username": "user",
        "password": "pass"
    }
)
```

---

## Rate Limiting Strategies

### RPM-Based Rate Limiting

**Requests Per Minute**: Simple rate limiting based on requests per minute.

```python
config = {
    "url": "https://example.com",
    "max_rpm": 60  # 1 request per second
}
```

**Common RPM Values**:
- `max_rpm: 6` → 1 request every 10 seconds (very polite)
- `max_rpm: 30` → 1 request every 2 seconds (polite)
- `max_rpm: 60` → 1 request per second (default)
- `max_rpm: 120` → 2 requests per second (aggressive)

### Fixed Delay Rate Limiting

**Request Delay**: Fixed delay between requests in milliseconds.

```python
config = {
    "url": "https://example.com",
    "request_delay": 2000  # 2 second delay between requests
}
```

**Note**: `request_delay` overrides `max_rpm` when set.

**Common Delay Values**:
- `request_delay: 5000` → 5 second delay (very polite)
- `request_delay: 2000` → 2 second delay (polite)
- `request_delay: 1000` → 1 second delay (default)
- `request_delay: 500` → 0.5 second delay (fast)

### Adaptive Rate Limiting

Implement custom adaptive rate limiting:

```python
class AdaptiveRateLimiter(RateLimiter):
    def __init__(self, initial_rpm: int):
        super().__init__(initial_rpm)
        self.error_count = 0
        self.success_count = 0

    async def acquire(self):
        # Slow down on errors
        if self.error_count > 5:
            self.max_rpm = max(10, self.max_rpm // 2)
            self.error_count = 0

        # Speed up on success
        if self.success_count > 20:
            self.max_rpm = min(120, self.max_rpm * 1.5)
            self.success_count = 0

        await super().acquire()

    def record_error(self):
        self.error_count += 1

    def record_success(self):
        self.success_count += 1
```

### Domain-Specific Rate Limits

```python
DOMAIN_RATE_LIMITS = {
    "wikipedia.org": {"max_rpm": 60},
    "github.com": {"max_rpm": 30},
    "news.ycombinator.com": {"request_delay": 3000},
    "default": {"max_rpm": 60}
}

def get_rate_limit_for_domain(url: str):
    domain = urlparse(url).netloc
    return DOMAIN_RATE_LIMITS.get(domain, DOMAIN_RATE_LIMITS["default"])
```

---

## Performance Tuning

### Concurrency Configuration

**max_concurrency**: Number of parallel requests.

```python
# Conservative (for slow servers or respectful crawling)
"max_concurrency": 1

# Moderate (balanced)
"max_concurrency": 4

# Aggressive (for fast servers)
"max_concurrency": 10

# Maximum (use with caution)
"max_concurrency": 20
```

### Performance Profiles

#### High Speed Profile
```python
{
    "max_concurrency": 10,
    "max_rpm": 120,
    "skip_images": True,
    "request_delay": None
}
```

#### Balanced Profile
```python
{
    "max_concurrency": 4,
    "max_rpm": 60,
    "skip_images": False,
    "request_delay": None
}
```

#### Polite Profile
```python
{
    "max_concurrency": 2,
    "max_rpm": 30,
    "skip_images": False,
    "request_delay": 2000
}
```

#### Stealth Profile
```python
{
    "max_concurrency": 1,
    "request_delay": 5000,
    "skip_images": False
}
```

### Memory Optimization

```python
# Batch processing for large crawls
def batch_crawl(urls, batch_size=100):
    for i in range(0, len(urls), batch_size):
        batch = urls[i:i+batch_size]
        config = {
            "url": batch[0],  # Use discovery mode or sitemap
            "max_pages": len(batch),
            "max_concurrency": 4,
            "skip_images": True
        }
        submit_crawl(config)
```

### Disk I/O Optimization

```python
# Buffer writes
class BufferedWriter:
    def __init__(self, buffer_size=10):
        self.buffer = []
        self.buffer_size = buffer_size

    async def add(self, data):
        self.buffer.append(data)
        if len(self.buffer) >= self.buffer_size:
            await self.flush()

    async def flush(self):
        # Write all buffered data
        for data in self.buffer:
            await write_to_disk(data)
        self.buffer.clear()
```

---

## Custom Data Extractors

### Adding Custom Selectors

Modify `extract_page_data` in `crawler_service.py`:

```python
async def extract_page_data(self, url: str, crawler: AsyncWebCrawler):
    # ... existing code ...

    # Custom: Extract author
    author = []
    author_elem = soup.select_one(".author, .byline, [rel='author']")
    if author_elem:
        author.append(author_elem.text.strip())

    # Custom: Extract keywords
    keywords = []
    meta_keywords = soup.find('meta', attrs={'name': 'keywords'})
    if meta_keywords:
        keywords = [k.strip() for k in meta_keywords.get('content', '').split(',')]

    # Custom: Extract description
    description = []
    meta_desc = soup.find('meta', attrs={'name': 'description'})
    if meta_desc:
        description.append(meta_desc.get('content', '').strip())

    page_data = {
        'title': title,
        'page_url': [url],
        'meta_img_url': meta_img_url,
        'images': downloaded_images,
        'date': dates,
        # Custom fields
        'author': author,
        'keywords': keywords,
        'description': description
    }
```

### Schema-Based Extraction

```python
EXTRACTION_SCHEMA = {
    "title": {
        "selectors": ["h1", ".title", "title"],
        "attribute": "text"
    },
    "date": {
        "selectors": ["time", ".date", "[itemprop='datePublished']"],
        "attribute": "datetime|text"
    },
    "author": {
        "selectors": [".author", ".byline", "[rel='author']"],
        "attribute": "text"
    }
}

def extract_by_schema(soup, schema):
    results = {}
    for field, config in schema.items():
        values = []
        for selector in config['selectors']:
            elements = soup.select(selector)
            for elem in elements:
                if config['attribute'] == 'text':
                    values.append(elem.text.strip())
                else:
                    # Try multiple attributes
                    attrs = config['attribute'].split('|')
                    for attr in attrs:
                        val = elem.get(attr) if attr != 'text' else elem.text
                        if val:
                            values.append(val.strip())
                            break
        results[field] = values
    return results
```

---

## Image Handling

### Image Exceptions

Exclude images from specific page elements:

```python
config = {
    "url": "https://example.com",
    "skip_images": False,
    "image_exceptions": ".header, .footer, .sidebar, .ads"
}
```

**Common Image Exceptions**:
```python
# Exclude navigation and ads
"image_exceptions": ".header, .footer, .nav, .ad, .advertisement"

# Exclude social media icons
"image_exceptions": ".social, .share, .icon"

# Exclude thumbnails
"image_exceptions": ".thumb, .thumbnail, .preview"

# Complex selector
"image_exceptions": ".header img, .footer img, div[class*='ad'] img"
```

### Image Download Configuration

```python
# Customize image downloading
async def download_image_with_config(self, image_url: str, session: aiohttp.ClientSession):
    try:
        # Add custom headers
        headers = {
            "User-Agent": "MyCrawler/1.0",
            "Referer": self.current_page_url
        }

        async with session.get(
            image_url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            if response.status == 200:
                # Check file size
                content_length = response.headers.get('Content-Length')
                if content_length and int(content_length) > 10 * 1024 * 1024:  # 10MB
                    print(f"Skipping large image: {image_url}")
                    return None

                # Check content type
                content_type = response.headers.get('Content-Type', '')
                if not content_type.startswith('image/'):
                    print(f"Not an image: {image_url}")
                    return None

                # Download and save
                # ... existing code ...
    except Exception as e:
        print(f"Error downloading image {image_url}: {e}")
        return None
```

### Image Format Filtering

```python
ALLOWED_IMAGE_FORMATS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}

def should_download_image(image_url: str) -> bool:
    parsed = urlparse(image_url)
    ext = os.path.splitext(parsed.path)[1].lower()
    return ext in ALLOWED_IMAGE_FORMATS
```

---

## Output Configuration

### Custom Output Structure

```python
# Customize output directory structure
def create_output_structure(base_dir: Path, label: str):
    output_dir = base_dir / label
    (output_dir / "images").mkdir(parents=True, exist_ok=True)
    (output_dir / "json").mkdir(parents=True, exist_ok=True)
    (output_dir / "markdown").mkdir(parents=True, exist_ok=True)
    (output_dir / "metadata").mkdir(parents=True, exist_ok=True)
    return output_dir
```

### Output Formats

#### JSON Output
```python
# Customize JSON output
async def save_json_data(self, page_data: Dict, page_number: int):
    json_data = {
        "metadata": {
            "crawled_at": datetime.now().isoformat(),
            "page_number": page_number,
            "job_label": self.config.label
        },
        "data": page_data['data']
    }

    json_filename = self.output_dir / "json" / f"page_{page_number:05d}.json"
    async with aiofiles.open(json_filename, 'w', encoding='utf-8') as f:
        await f.write(json.dumps(json_data, indent=2, ensure_ascii=False))
```

#### CSV Output
```python
import csv

async def save_as_csv(self, all_pages_data: List[Dict], filename: str):
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['title', 'url', 'date', 'author'])
        writer.writeheader()
        for page in all_pages_data:
            writer.writerow({
                'title': page['title'][0] if page['title'] else '',
                'url': page['page_url'][0] if page['page_url'] else '',
                'date': page['date'][0] if page['date'] else '',
                'author': page.get('author', [''])[0]
            })
```

---

## Advanced Examples

### Example 1: News Site Crawler

```python
config = {
    "url": "https://news.example.com",
    "max_pages": 100,
    "discovery_mode": True,
    "max_concurrency": 3,
    "max_rpm": 30,
    "skip_images": False,
    "image_exceptions": ".header, .footer, .sidebar, .ads",
    "date_selector": "time[datetime], .published-date, meta[property='article:published_time']",
    "label": "news_site_crawl"
}
```

### Example 2: E-commerce Product Crawler

```python
config = {
    "url": "https://shop.example.com/sitemap.xml",
    "max_pages": 500,
    "max_concurrency": 5,
    "max_rpm": 60,
    "skip_images": False,
    "image_exceptions": ".header, .footer, .nav, .breadcrumb",
    "label": "product_catalog"
}
```

### Example 3: Documentation Site

```python
config = {
    "url": "https://docs.example.com",
    "max_pages": 200,
    "discovery_mode": True,
    "max_concurrency": 2,
    "request_delay": 1000,
    "skip_images": True,
    "label": "docs_snapshot"
}
```

### Example 4: Blog Archive

```python
config = {
    "url": "https://blog.example.com/sitemap.xml",
    "max_pages": 1000,
    "max_concurrency": 4,
    "max_rpm": 60,
    "skip_images": False,
    "date_selector": "time, .post-date, meta[property='article:published_time']",
    "label": "blog_archive_2025"
}
```

---

## Configuration Best Practices

1. **Start Conservative**: Begin with low concurrency and RPM, then increase
2. **Test First**: Test with `max_pages: 5` before large crawls
3. **Respect robots.txt**: Check site's robots.txt for crawl delays
4. **Use Appropriate Labels**: Use descriptive labels for organization
5. **Monitor Resources**: Watch CPU, memory, and disk usage
6. **Handle Errors**: Implement proper error handling and logging
7. **Backup Configuration**: Save successful configurations
8. **Document Custom Extractors**: Document any custom data extraction logic

---

## Configuration Validation

```python
def validate_config(config: dict) -> tuple[bool, str]:
    """Validate configuration before submission"""

    # Check required fields
    if 'url' not in config:
        return False, "URL is required"

    # Validate concurrency
    if config.get('max_concurrency', 4) > 20:
        return False, "max_concurrency must be <= 20"

    # Validate RPM
    if config.get('max_rpm', 60) < 1:
        return False, "max_rpm must be >= 1"

    # Validate delay
    delay = config.get('request_delay')
    if delay is not None and delay < 0:
        return False, "request_delay must be >= 0"

    # Check for conflicting settings
    if config.get('skip_images') and config.get('image_exceptions'):
        return False, "image_exceptions ignored when skip_images is true"

    return True, "Configuration valid"
```

---

Your crawler is now fully configured and optimized for your use case!

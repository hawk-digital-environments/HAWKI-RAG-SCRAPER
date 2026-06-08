# Developer Guide

This guide helps developers understand the CustomCrawler codebase, including the Python crawler backend and the SvelteKit admin UI in `ui/`.

## Table of Contents

- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Code Style & Standards](#code-style--standards)
- [Understanding the Codebase](#understanding-the-codebase)
- [Adding New Features](#adding-new-features)
- [Testing](#testing)
- [Debugging](#debugging)
- [Contributing](#contributing)
- [Common Development Tasks](#common-development-tasks)

---

## Development Setup

### 1. Prerequisites

- Python 3.9 or higher
- Node.js and npm for the SvelteKit UI
- Docker and Docker Compose for the crawler/RabbitMQ stack
- GNU Make for project shortcuts
- Git
- Code editor (VS Code recommended)
- Basic understanding of Python async code, Docker, SvelteKit, and TypeScript

### 2. Clone Repository

```bash
git clone <repository-url>
cd CustomCrawler
```

### 3. Create Virtual Environment

```bash
# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
# On macOS/Linux:
source .venv/bin/activate

# On Windows:
.venv\Scripts\activate
```

### 4. Install Dependencies

```bash
# Install production dependencies
pip install -r requirements.txt

# Install development dependencies
pip install pytest pytest-asyncio pytest-cov black pylint mypy httpx

# Install Playwright browsers
playwright install
```

### 5. Install Pre-commit Hooks (Optional)

```bash
pip install pre-commit
pre-commit install
```

Create `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.3.0
    hooks:
      - id: black
        language_version: python3.11

  - repo: https://github.com/PyCQA/pylint
    rev: v3.0.0
    hooks:
      - id: pylint
        args: [--max-line-length=100]

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.3.0
    hooks:
      - id: mypy
        additional_dependencies: [types-all]
```

### 6. Configure IDE

#### VS Code Settings

Create `.vscode/settings.json`:

```json
{
  "python.linting.enabled": true,
  "python.linting.pylintEnabled": true,
  "python.formatting.provider": "black",
  "editor.formatOnSave": true,
  "python.linting.pylintArgs": ["--max-line-length=100"],
  "[python]": {
    "editor.defaultFormatter": "ms-python.black-formatter",
    "editor.codeActionsOnSave": {
      "source.organizeImports": true
    }
  }
}
```

### 7. Run Backend Stack

```bash
make up
```

The crawler API is proxied by the UI through `ui/src/routes/api/crawler/*`. By default the UI server tries `CRAWLER_API_BASE_URL`, then falls back to `http://localhost:8040` and `http://localhost:8000`.

### 8. Run the UI

Use the Makefile target from the repository root:

```bash
make start-ui
```

`make start-ui` runs:

```bash
npm install --prefix ui
npm --prefix ui run dev
```

This starts the SvelteKit development server for `ui/`. You can also run the commands manually:

```bash
cd ui
npm install
npm run dev
```

Useful UI environment variables:

```bash
PUBLIC_API_BASE_URL=
CRAWLER_API_BASE_URL=http://localhost:8040
RABBITMQ_MGMT_API_URL=http://localhost:15672/api
RABBITMQ_MGMT_USER=guest
RABBITMQ_MGMT_PASSWORD=guest
PROFILES_HOST_DIR=../profiles
PROFILES_CONTAINER_DIR=/var/www/html/profiles
```

Leave `PUBLIC_API_BASE_URL` empty for normal local development so browser calls use the same-origin SvelteKit API routes.

---

## Project Structure

```text
CustomCrawler/
├── Makefile                         # Root developer/operator shortcuts
├── docker-compose.yml               # Service orchestration
├── profiles/                        # Crawler profile JSON files
├── hawki_crawler/                   # Python crawler/backend modules
│   ├── app/main.py
│   ├── crawler/
│   ├── common/
│   ├── rabbitmq/
│   └── services/
├── ui/                              # SvelteKit admin UI
│   ├── package.json
│   ├── src/var/www/html.css
│   ├── src/lib/api/
│   ├── src/lib/components/
│   ├── src/lib/server/
│   ├── src/lib/ui/
│   └── src/routes/
└── _documentation/                  # Project documentation
```

### File Responsibilities

| File or folder | Purpose |
|----------------|---------|
| `Makefile` | Project shortcuts for crawling, Docker lifecycle, job cancellation, shared-output cleanup, and UI startup. |
| `hawki_crawler/var/www/html/main.py` | Python crawler API entrypoint. |
| `hawki_crawler/crawler/` | Crawling logic, profile loading, sitemap parsing, URL policy, content parsing, storage, progress tracking. |
| `hawki_crawler/common/` | Shared job schemas, logging setup, pipeline event definitions. |
| `hawki_crawler/rabbitmq/` | RabbitMQ producer/communication helpers. |
| `profiles/` | JSON profile files used by crawler jobs and editable from the UI. |
| `ui/src/routes/` | SvelteKit UI pages and SvelteKit API routes. |
| `ui/src/lib/api/index.ts` | Production UI HTTP client. All UI API calls should go through this file. |
| `ui/src/lib/api/types.ts` | Shared TypeScript models for UI pages and components. |
| `ui/src/lib/api/stub.ts` | Mock data layer for local experiments only; do not import by default. |
| `ui/src/lib/ui/` | Generic UI primitives such as buttons, badges, tables, cards, alerts, and page layout. |
| `ui/src/lib/components/` | Crawler-specific forms and widgets such as `ProfileForm`, `TaskForm`, `EntrypointList`, and `ConfirmDialog`. |
| `ui/src/lib/server/` | Server-only SvelteKit helpers for crawler/RabbitMQ API configuration and fetch fallback. |

### UI Route Responsibilities

| Route | Responsibility |
|-------|----------------|
| `/` | Running jobs dashboard and RabbitMQ queue overview. |
| `/jobs/[jobId]` | Job detail page. Reads `jobId` from params, loads job state, polls while running, and sends cancel requests. |
| `/profiles` | Lists profile JSON files. |
| `/profiles/new` | Creates a new profile JSON file. |
| `/profiles/[profileId]` | Shows one profile, including entrypoints, discovery, forbidden rules, content settings, and JSON preview. |
| `/profiles/[profileId]/edit` | Edits one profile JSON file. |
| `/tasks` | Lists derived manual crawl tasks, one per profile. |
| `/tasks/new` | Task creation form surface. Current backend does not persist tasks, so tasks are derived until that API exists. |
| `/tasks/[taskId]` | Task detail and start-now action. |
| `/tasks/[taskId]/edit` | Task edit surface for future task persistence. |

### UI API Route Responsibilities

| Endpoint | Responsibility |
|----------|----------------|
| `GET /api/profiles` | Lists profile files from `PROFILES_HOST_DIR`. |
| `POST /api/profiles` | Writes a new profile JSON file. |
| `GET /api/profiles/[name]` | Reads one profile file or `.json.example`. |
| `PUT /api/profiles/[name]` | Updates one profile file. |
| `POST /api/crawler/submit` | Proxies to crawler `POST /crawl`. |
| `GET /api/crawler/jobs` | Proxies to crawler `GET /jobs`. |
| `POST /api/crawler/job/[jobId]/cancel` | Proxies a job cancel request. |
| `GET /api/crawler/job/[jobId]/summary` | Reads crawler output metadata and derives URL counts. |
| `GET /api/rabbitmq/queues` | Proxies RabbitMQ management queue state. |

### UI Component Responsibilities

| Component | Responsibility |
|-----------|----------------|
| `PageContent` | Shared page header and white content panel. |
| `Button`, `Card`, `Badge`, `Alert`, `TableWrap`, `Breadcrumb`, `EmptyState` | Generic visual primitives used by all routes. |
| `FormGroup`, `TextInput`, `SelectInput` | Shared form structure and controls. |
| `ProfileForm` | Builds profile input data for profile create/edit screens. |
| `TaskForm` | Builds task input data and validates optional cron expressions. |
| `EntrypointList`, `DynamicList`, `DurationInput` | Reusable nested form controls for profile/task editing. |
| `ConfirmDialog` | Confirmation UI for destructive actions. |

---

## Code Style & Standards

### Python Style Guide

Follow PEP 8 with these specifications:

- **Line Length**: Max 100 characters
- **Indentation**: 4 spaces
- **Quotes**: Double quotes for strings
- **Naming Conventions**:
  - Classes: `PascalCase`
  - Functions/Methods: `snake_case`
  - Constants: `UPPER_SNAKE_CASE`
  - Private methods: `_leading_underscore`

### Type Hints

Use type hints for all function signatures:

```python
from typing import List, Dict, Optional

async def extract_page_data(
    self,
    url: str,
    crawler: AsyncWebCrawler
) -> Optional[Dict]:
    """Extract data from a single page"""
    pass
```

### Docstrings

Use Google-style docstrings:

```python
def parse_sitemap(self, sitemap_url: str) -> List[str]:
    """Parse sitemap and extract URLs.

    Args:
        sitemap_url: URL of the sitemap to parse

    Returns:
        List of URLs found in the sitemap

    Raises:
        aiohttp.ClientError: If sitemap cannot be fetched
    """
    pass
```

### Code Formatting

Format code with Black:

```bash
# Format all Python files
black .

# Check formatting without making changes
black --check .
```

### Linting

Run Pylint to check code quality:

```bash
# Lint all Python files
pylint *.py

# Lint specific file
pylint main.py
```

### Type Checking

Use mypy for static type checking:

```bash
# Type check all files
mypy .

# Type check specific file
mypy main.py
```

---

## Understanding the Codebase

### Request Flow

```python
# 1. Client submits crawl request
POST /crawl → crawl() in main.py

# 2. Validate configuration
CrawlConfig validates input (models.py)

# 3. Create job
Generate UUID, create CrawlStatus, store in jobs dict

# 4. Schedule background task
BackgroundTasks.add_task(run_crawl_job, ...)

# 5. Return immediately
Return job_id to client

# 6. Background execution
run_crawl_job() → CrawlerService.crawl()

# 7. Crawling
- Setup directories
- Parse sitemap or start URL discovery
- Loop through URLs
  - Rate limiting
  - Fetch page with Playwright
  - Extract data
  - Download images
  - Save files
  - Discover new URLs (if enabled)

# 8. Complete
Update job status to "completed" or "failed"
```

### Key Classes

#### CrawlConfig (models.py)
```python
class CrawlConfig(BaseModel):
    """Configuration for crawl job"""
    # Validates and stores crawl configuration
    # Provides default values
    # Enforces constraints (e.g., max_concurrency <= 20)
```

#### CrawlStatus (models.py)
```python
class CrawlStatus(BaseModel):
    """Status response for crawl job"""
    # Tracks job lifecycle
    # Stores progress information
    # Provides timestamps
```

#### RateLimiter (crawler_service.py)
```python
class RateLimiter:
    """Rate limiter to control request frequency"""
    # Implements RPM-based or fixed-delay rate limiting
    # Thread-safe using asyncio.Lock
    # Calculates wait times between requests
```

#### CrawlerService (crawler_service.py)
```python
class CrawlerService:
    """Main crawler service handling all crawling operations"""
    # Orchestrates entire crawl process
    # Manages URL queue (to_visit, visited_urls)
    # Handles sitemap parsing
    # Coordinates concurrent crawling
    # Extracts and saves data
```

### Important Methods

#### CrawlerService.crawl()
Main entry point for crawling:

```python
async def crawl(self) -> Dict:
    """Main crawl method"""
    # 1. Setup output directories
    # 2. Detect if URL is sitemap
    # 3. Parse sitemap or add starting URL
    # 4. Initialize browser
    # 5. Loop through URLs in batches
    # 6. Process each batch concurrently
    # 7. Return results
```

#### CrawlerService.extract_page_data()
Extracts data from a single page:

```python
async def extract_page_data(
    self,
    url: str,
    crawler: AsyncWebCrawler
) -> Optional[Dict]:
    """Extract data from a single page"""
    # 1. Wait for rate limiter
    # 2. Fetch page with crawl4ai
    # 3. Parse HTML with BeautifulSoup
    # 4. Extract title, images, dates, etc.
    # 5. Download images
    # 6. Return structured data
```

#### CrawlerService.discover_urls()
Discovers internal links:

```python
async def discover_urls(
    self,
    html_content: str,
    base_url: str
) -> List[str]:
    """Discover URLs from HTML content"""
    # 1. Parse HTML
    # 2. Find all <a> tags
    # 3. Filter for same-domain URLs
    # 4. Normalize URLs
    # 5. Return unique URLs
```

---

## Adding New Features

### Example: Add a Custom Field Extractor

#### 1. Add Field to PageData Model

```python
# models.py
class PageData(BaseModel):
    """Data structure for a single crawled page"""
    title: List[str]
    page_url: List[str]
    meta_img_url: List[str]
    images: List[str]
    date: List[str]
    author: List[str]  # New field
```

#### 2. Add Configuration Parameter

```python
# models.py
class CrawlConfig(BaseModel):
    # ... existing fields ...
    author_selector: Optional[str] = Field(
        default=None,
        description="CSS selector for author elements"
    )
```

#### 3. Implement Extraction Logic

```python
# crawler_service.py
async def extract_page_data(self, url: str, crawler: AsyncWebCrawler):
    # ... existing code ...

    # Extract author
    authors = []
    if self.config.author_selector:
        author_elements = soup.select(self.config.author_selector)
        for elem in author_elements:
            author_text = elem.text.strip()
            if author_text:
                authors.append(author_text)

    page_data = {
        'title': title,
        'page_url': [url],
        'meta_img_url': meta_img_url,
        'images': downloaded_images,
        'date': dates,
        'author': authors  # Add new field
    }

    return {
        'data': page_data,
        'markdown': result.markdown,
        'html_content': result.html
    }
```

#### 4. Update API Documentation

```python
# main.py - Update docstring
@app.post("/crawl", response_model=CrawlResponse)
async def crawl(config: CrawlConfig, background_tasks: BackgroundTasks):
    """
    Submit a crawl job

    Parameters:
    - ...existing params...
    - author_selector: CSS selector for author elements
    """
```

#### 5. Write Tests

```python
# tests/test_crawler.py
@pytest.mark.asyncio
async def test_extract_author():
    """Test author extraction"""
    html = """
    <html>
        <head><title>Test</title></head>
        <body>
            <div class="author">John Doe</div>
        </body>
    </html>
    """

    config = CrawlConfig(
        url="https://example.com",
        author_selector=".author"
    )

    crawler = CrawlerService(config)
    # ... test extraction logic
```

### Example: Add Webhook Support

#### 1. Add Webhook Configuration

```python
# models.py
class CrawlConfig(BaseModel):
    # ... existing fields ...
    webhook_url: Optional[HttpUrl] = Field(
        default=None,
        description="Webhook URL to notify on completion"
    )
```

#### 2. Implement Webhook Notification

```python
# main.py
async def notify_webhook(webhook_url: str, job_id: str, status: str):
    """Send webhook notification"""
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "job_id": job_id,
                "status": status,
                "timestamp": datetime.now().isoformat()
            }
            async with session.post(
                webhook_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status != 200:
                    print(f"Webhook failed: {response.status}")
    except Exception as e:
        print(f"Webhook error: {e}")

async def run_crawl_job(job_id: str, config: CrawlConfig):
    """Background task to run crawl job"""
    try:
        # ... existing crawl logic ...

        jobs[job_id].status = "completed"

        # Send webhook notification
        if config.webhook_url:
            await notify_webhook(
                str(config.webhook_url),
                job_id,
                "completed"
            )

    except Exception as e:
        jobs[job_id].status = "failed"

        # Send webhook notification on failure
        if config.webhook_url:
            await notify_webhook(
                str(config.webhook_url),
                job_id,
                "failed"
            )
```

---

## Testing

### Test Structure

```
tests/
├── __init__.py
├── conftest.py           # Shared fixtures
├── test_api.py          # API endpoint tests
├── test_crawler.py      # Crawler service tests
├── test_models.py       # Model validation tests
└── test_integration.py  # End-to-end tests
```

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_api.py

# Run specific test
pytest tests/test_api.py::test_submit_crawl

# Run with coverage
pytest --cov=. --cov-report=html

# View coverage report
open htmlcov/index.html
```

### Writing Tests

#### Unit Test Example

```python
# tests/test_models.py
import pytest
from pydantic import ValidationError
from models import CrawlConfig

def test_crawl_config_valid():
    """Test valid crawl configuration"""
    config = CrawlConfig(
        url="https://example.com",
        max_pages=50
    )
    assert config.url == "https://example.com"
    assert config.max_pages == 50

def test_crawl_config_invalid_url():
    """Test invalid URL validation"""
    with pytest.raises(ValidationError):
        CrawlConfig(url="not-a-url")

def test_crawl_config_max_concurrency():
    """Test max_concurrency constraint"""
    with pytest.raises(ValidationError):
        CrawlConfig(
            url="https://example.com",
            max_concurrency=25  # Exceeds max of 20
        )
```

#### API Test Example

```python
# tests/test_api.py
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_root_endpoint():
    """Test root endpoint"""
    response = client.get("/")
    assert response.status_code == 200
    assert "message" in response.json()

def test_submit_crawl():
    """Test crawl submission"""
    config = {
        "url": "https://example.com",
        "max_pages": 5
    }
    response = client.post("/crawl", json=config)
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert data["status"] == "pending"

def test_get_status_not_found():
    """Test status check for non-existent job"""
    response = client.get("/status/invalid-job-id")
    assert response.status_code == 404
```

#### Async Test Example

```python
# tests/test_crawler.py
import pytest
from crawler_service import CrawlerService, RateLimiter
from models import CrawlConfig
import time

@pytest.mark.asyncio
async def test_rate_limiter():
    """Test rate limiting functionality"""
    limiter = RateLimiter(max_rpm=60)  # 1 request per second

    start = time.time()
    await limiter.acquire()
    await limiter.acquire()
    elapsed = time.time() - start

    assert elapsed >= 1.0, "Rate limiter should enforce 1 second delay"

@pytest.mark.asyncio
async def test_url_normalization():
    """Test URL normalization"""
    config = CrawlConfig(url="https://example.com")
    crawler = CrawlerService(config)

    # Test various URL formats
    url1 = crawler.normalize_url("https://example.com/page#section")
    url2 = crawler.normalize_url("https://example.com/page/")
    url3 = crawler.normalize_url("https://example.com/page")

    assert url1 == "https://example.com/page"
    assert url2 == "https://example.com/page"
    assert url3 == "https://example.com/page"
```

### Test Fixtures

```python
# tests/conftest.py
import pytest
from models import CrawlConfig

@pytest.fixture
def sample_config():
    """Fixture for sample crawl configuration"""
    return CrawlConfig(
        url="https://example.com",
        max_pages=10,
        skip_images=True
    )

@pytest.fixture
def sample_html():
    """Fixture for sample HTML content"""
    return """
    <html>
        <head><title>Test Page</title></head>
        <body>
            <h1>Test Content</h1>
            <a href="/page1">Link 1</a>
            <a href="/page2">Link 2</a>
            <img src="/image.jpg" />
        </body>
    </html>
    """
```

---

## Debugging

### Enable Debug Logging

```python
# main.py
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)
```

### Debug Mode in IDE

#### VS Code Launch Configuration

Create `.vscode/launch.json`:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: FastAPI",
      "type": "python",
      "request": "launch",
      "module": "uvicorn",
      "args": [
        "main:app",
        "--reload",
        "--host",
        "0.0.0.0",
        "--port",
        "8000"
      ],
      "jinja": true,
      "justMyCode": false
    }
  ]
}
```

### Common Debugging Tasks

#### Print Job Status

```python
# Add to main.py
@app.get("/debug/jobs")
async def debug_jobs():
    """Debug endpoint to view all job details"""
    return {
        job_id: {
            **status.dict(),
            "started_at": status.started_at.isoformat(),
            "completed_at": status.completed_at.isoformat() if status.completed_at else None
        }
        for job_id, status in jobs.items()
    }
```

#### Trace URL Discovery

```python
# In crawler_service.py
async def discover_urls(self, html_content: str, base_url: str):
    urls = []
    soup = BeautifulSoup(html_content, 'html.parser')
    base_domain = urlparse(base_url).netloc

    for link in soup.find_all('a', href=True):
        href = link['href']
        absolute_url = urljoin(base_url, href)
        parsed = urlparse(absolute_url)

        # Debug logging
        print(f"Found link: {href}")
        print(f"  Absolute: {absolute_url}")
        print(f"  Domain: {parsed.netloc} (base: {base_domain})")

        if parsed.netloc == base_domain:
            normalized = self.normalize_url(absolute_url)
            urls.append(normalized)
            print(f"  ✓ Added: {normalized}")
        else:
            print(f"  ✗ Skipped: External domain")

    return urls
```

---

## Contributing

### Contribution Workflow

1. **Fork the repository**
2. **Create a feature branch**
   ```bash
   git checkout -b feature/amazing-feature
   ```

3. **Make changes**
   - Write code
   - Add tests
   - Update documentation

4. **Run tests**
   ```bash
   pytest
   black --check .
   pylint *.py
   mypy .
   ```

5. **Commit changes**
   ```bash
   git add .
   git commit -m "Add amazing feature"
   ```

6. **Push to your fork**
   ```bash
   git push origin feature/amazing-feature
   ```

7. **Open a Pull Request**

### Commit Message Guidelines

Format: `<type>: <subject>`

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

Examples:
```
feat: Add webhook support for job completion
fix: Handle sitemap parsing errors gracefully
docs: Update API reference with new endpoints
test: Add tests for rate limiter
refactor: Extract URL discovery into separate method
```

---

## Common Development Tasks

### Start the UI

```bash
make start-ui
```

### Check the UI

```bash
npm --prefix ui run check
```

### Build the UI

```bash
npm --prefix ui run build
```

### Start Backend Services

```bash
make up
```

### Stop Backend Services

```bash
make down
```

### Submit a Sample Crawl

```bash
make crawl-sample
```

### Cancel a Job

```bash
make cancel JOB_ID=<job_id>
```

### Add a New API Endpoint

```python
# main.py
@app.get("/jobs/{job_id}/results")
async def get_job_results(job_id: str):
    """Get crawl results for a completed job"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    if job.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Job is {job.status}, not completed"
        )

    # Read all result files
    output_dir = Path(job.output_directory)
    results = []

    for json_file in sorted(output_dir.glob("data_*.json")):
        async with aiofiles.open(json_file, 'r') as f:
            content = await f.read()
            results.append(json.loads(content))

    return {
        "job_id": job_id,
        "total_pages": len(results),
        "results": results
    }
```

### Add Custom Middleware

```python
# main.py
from fastapi import Request
import time

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Add X-Process-Time header to responses"""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response
```

### Create a Custom Exception Handler

```python
# main.py
from fastapi.responses import JSONResponse

class CrawlerException(Exception):
    """Custom exception for crawler errors"""
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code

@app.exception_handler(CrawlerException)
async def crawler_exception_handler(request: Request, exc: CrawlerException):
    """Handle crawler-specific exceptions"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.message}
    )
```

---

## Resources

### Documentation
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [Playwright Python Documentation](https://playwright.dev/python/)
- [BeautifulSoup Documentation](https://www.crummy.com/software/BeautifulSoup/bs4/doc/)
- [crawl4ai Documentation](https://github.com/unclecode/crawl4ai)

### Tools
- [Black Code Formatter](https://black.readthedocs.io/)
- [Pylint](https://pylint.pycqa.org/)
- [pytest](https://docs.pytest.org/)
- [mypy](http://mypy-lang.org/)

---

Happy coding! If you have questions, please open an issue or discussion on the repository.

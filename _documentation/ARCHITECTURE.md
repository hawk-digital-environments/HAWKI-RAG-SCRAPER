# Architecture

This document describes the current CustomCrawler architecture: the Python crawler service, profile-driven crawl configuration, RabbitMQ visibility, and the SvelteKit admin UI.

## Overview

CustomCrawler is a web scraping and crawling system. The backend accepts crawl jobs, manages crawler execution, stores output in shared volumes, and exposes job state. The UI is a SvelteKit application under `ui/` that gives operators a structured admin surface for running jobs, editing profile JSON files, viewing queue state, and inspecting job details.

The UI replacement in this branch is source-based SvelteKit, not generated `.svelte-kit` output. Generated files under `ui/.svelte-kit/` are build artifacts and should not be edited.

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Operator Layer                        │
│  Browser UI, cURL, Make targets, Python scripts             │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            │ HTTP
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                     SvelteKit UI (`ui/`)                    │
│  Pages: /, /jobs/[jobId], /profiles, /tasks                 │
│  Components: ui/, components/, utils/                       │
│  Client facade: src/lib/api/index.ts                        │
└───────────────┬───────────────────────────────┬─────────────┘
                │ same-origin /api by default   │ optional PUBLIC_API_BASE_URL
                │                               │
┌───────────────▼───────────────────────────────▼─────────────┐
│                 SvelteKit API Routes (`ui/src/routes/api`)   │
│  • /api/profiles             profile file read/write         │
│  • /api/crawler/submit       proxy to crawler /crawl         │
│  • /api/crawler/jobs         proxy to crawler /jobs          │
│  • /api/crawler/job/...      cancel and summary helpers      │
│  • /api/rabbitmq/queues      proxy to RabbitMQ management    │
└───────────────┬───────────────────────────────┬─────────────┘
                │                               │
┌───────────────▼──────────────┐     ┌──────────▼─────────────┐
│ Python Crawler API/Service    │     │ RabbitMQ Management API │
│ POST /crawl, GET /jobs,       │     │ Queue depth/consumer    │
│ POST /jobs/{jobId}/cancel     │     │ state                   │
└───────────────┬──────────────┘     └────────────────────────┘
                │
┌───────────────▼─────────────────────────────────────────────┐
│ Crawler runtime, profile loading, sitemap parsing,          │
│ URL discovery, page extraction, file output, shared volumes  │
└─────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. SvelteKit UI (`ui/`)

**Responsibility**: Browser-facing admin interface for operators.

**Key files**:

| File or folder | Responsibility |
|----------------|----------------|
| `ui/src/app.css` | Global design tokens, colors, typography, reset, and shared layout variables. |
| `ui/src/routes/+layout.svelte` | Fixed sidebar, route navigation, active route detection, app shell. |
| `ui/src/routes/+layout.ts` | Disables SSR for the UI shell with `ssr = false`; the UI runs as a browser app against API routes. |
| `ui/src/lib/api/index.ts` | Real fetch-based typed API client. All production UI data access goes through this file. |
| `ui/src/lib/api/types.ts` | UI-facing TypeScript models: `Profile`, `Task`, `Job`, `Queue`, entrypoints, status enums. |
| `ui/src/lib/api/stub.ts` | Mock/in-memory API retained for local experiments only; not imported by production routes. |
| `ui/src/lib/ui/` | Reusable visual primitives such as buttons, cards, badges, forms, page layout, tables, alerts. |
| `ui/src/lib/components/` | Domain components for crawler workflows: profile form, task form, dynamic lists, duration inputs, dialogs. |
| `ui/src/lib/utils/` | Small shared helpers, currently duration parsing/formatting. |

### 2. UI Route Responsibilities

| Route | Files | Responsibility |
|-------|-------|----------------|
| `/` | `ui/src/routes/+page.ts`, `+page.svelte` | Running jobs dashboard. Loads running jobs, profiles, derived tasks, and RabbitMQ queues. Rows link to job details. |
| `/jobs/[jobId]` | `ui/src/routes/jobs/[jobId]/+page.ts`, `+page.svelte` | Job detail page. Reads `jobId` from route params, loads the matching job through the API client, shows status metadata and log-like status lines, polls while running, and can send stop requests. |
| `/profiles` | `ui/src/routes/profiles/+page.ts`, `+page.svelte` | Profile list. Loads profile JSON files through `/api/profiles`, shows entrypoint and retention summary, links to profile detail. |
| `/profiles/new` | `ui/src/routes/profiles/new/+page.svelte` | Profile creation form. Uses `ProfileForm` and posts through `createProfile()`. |
| `/profiles/[profileId]` | `ui/src/routes/profiles/[profileId]/+page.ts`, `+page.svelte` | Profile detail. Shows behavior, entrypoints, discovery, forbidden, content extraction settings, JSON preview, and create-task/edit actions. |
| `/profiles/[profileId]/edit` | `ui/src/routes/profiles/[profileId]/edit/+page.ts`, `+page.svelte` | Profile editing form. Uses `updateProfile()` and preserves the existing profile id/path. |
| `/tasks` | `ui/src/routes/tasks/+page.ts`, `+page.svelte` | Derived task list. Current backend has no persistent task API, so the UI derives one manual task per profile. Start buttons submit crawler jobs. |
| `/tasks/new` | `ui/src/routes/tasks/new/+page.ts`, `+page.svelte` | Task form surface. It creates a UI task object, but persistence is currently derived from profiles until a backend task API exists. |
| `/tasks/[taskId]` | `ui/src/routes/tasks/[taskId]/+page.ts`, `+page.svelte` | Derived task detail. Shows linked profile and recent jobs where available, and can start a crawl. |
| `/tasks/[taskId]/edit` | `ui/src/routes/tasks/[taskId]/edit/+page.ts`, `+page.svelte` | Task editing surface for future task persistence. Currently returns an updated UI task object only. |

### 3. UI Element Responsibilities

| Component | Responsibility |
|-----------|----------------|
| `PageContent.svelte` | Blue title band plus elevated white content panel used by every main UI screen. |
| `Button.svelte` | Shared button/link styling for primary, secondary, danger, ghost, and small/icon variants. |
| `Card.svelte` | Section wrapper with optional title, actions, footer, and no-padding table mode. |
| `TableWrap.svelte` | Responsive table wrapper and consistent table cell/header styling. |
| `Badge.svelte` | Status labels for running, stopping, completed, failed, cancelled, manual, scheduled. |
| `Alert.svelte` | Info, warning, success, and danger callouts. |
| `Breadcrumb.svelte` | Hierarchical navigation within detail/edit screens. |
| `EmptyState.svelte` | Standard empty list/message presentation. |
| `FormGroup.svelte` | Label, hint, error, and spacing wrapper for form controls. |
| `TextInput.svelte` / `SelectInput.svelte` | Typed, styled form controls used by profile/task forms. |
| `ProfileForm.svelte` | Builds `ProfileInput`: name, entrypoints, discovery hosts, forbidden rules, content extraction, retention, retry behavior. |
| `TaskForm.svelte` | Builds `TaskInput`: name, profile selection, optional cron schedule. |
| `EntrypointList.svelte` | Edits host/sitemap entrypoints and sitemap conflict-resolution metadata. |
| `DynamicList.svelte` | Reusable string-list editor for hosts, URL patterns, selectors, and phrases. |
| `DurationInput.svelte` | Splits duration strings such as `24h` or `7d` into amount/unit controls. |
| `ConfirmDialog.svelte` | Reusable destructive-action confirmation modal. |

### 4. SvelteKit API Routes

**Responsibility**: Keep browser code simple and protect backend details behind same-origin endpoints.

| Endpoint | File | Responsibility |
|----------|------|----------------|
| `GET /api/profiles` | `ui/src/routes/api/profiles/+server.js` | Lists profile JSON and `.json.example` files from `PROFILES_HOST_DIR`. |
| `POST /api/profiles` | `ui/src/routes/api/profiles/+server.js` | Validates a profile name and writes JSON to `PROFILES_HOST_DIR`. |
| `GET /api/profiles/[name]` | `ui/src/routes/api/profiles/[name]/+server.js` | Reads one profile JSON file, falling back to `.json.example`. |
| `PUT /api/profiles/[name]` | `ui/src/routes/api/profiles/[name]/+server.js` | Updates one writable profile JSON file. |
| `POST /api/crawler/submit` | `ui/src/routes/api/crawler/submit/+server.ts` | Proxies UI crawl submissions to crawler `POST /crawl`. |
| `GET /api/crawler/jobs` | `ui/src/routes/api/crawler/jobs/+server.ts` | Proxies crawler `GET /jobs`. |
| `POST /api/crawler/job/[jobId]/cancel` | `ui/src/routes/api/crawler/job/[jobId]/cancel/+server.ts` | Proxies crawler job cancellation. |
| `GET /api/crawler/job/[jobId]/summary` | `ui/src/routes/api/crawler/job/[jobId]/summary/+server.ts` | Reads crawler file APIs and derives URL counts for a job. |
| `GET /api/rabbitmq/queues` | `ui/src/routes/api/rabbitmq/queues/+server.ts` | Proxies RabbitMQ management queue state. |

### 5. UI API Client

`ui/src/lib/api/index.ts` is the only production import surface for UI pages and components. It:

- Reads `PUBLIC_API_BASE_URL` from public environment variables.
- Uses same-origin `/api/...` when `PUBLIC_API_BASE_URL` is unset.
- Throws `ApiError` for non-2xx responses.
- Maps backend profile file shapes into UI `Profile` objects.
- Maps crawler job payloads into UI `Job` objects.
- Maps RabbitMQ queue payloads into UI `Queue` objects.
- Derives manual tasks from profiles because the current backend has no persistent task API.

### 6. Python Crawler Application

**Responsibility**: HTTP request handling, routing, and API endpoint management.

**Key Features**:
- REST API endpoints for job submission and status checking
- CORS middleware for cross-origin requests
- Background task management using FastAPI's BackgroundTasks
- In-memory job status storage
- Request validation using Pydantic models

**Design Decisions**:
- Jobs are stored in memory (not persistent across restarts)
- Background tasks run asynchronously without blocking API responses
- UUID-based job IDs for unique identification

### 2. Data Models (models.py)

**Responsibility**: Data validation and serialization using Pydantic.

**Models**:

#### CrawlConfig
- Validates input parameters for crawl jobs
- Enforces constraints (e.g., max_concurrency: 1-20)
- Provides default values for optional parameters
- Uses Pydantic's HttpUrl for URL validation

#### CrawlStatus
- Tracks job lifecycle: pending → running → completed/failed
- Stores timestamps for job tracking
- Contains progress information (pages_crawled)

#### PageData
- Defines structure for extracted page data
- All fields are lists to accommodate multiple values
- Saved as JSON for each crawled page

### 3. Crawler Service (crawler_service.py)

**Responsibility**: Core crawling logic, data extraction, and file management.

**Key Components**:

#### RateLimiter
```python
class RateLimiter:
    - Controls request frequency
    - Supports RPM-based and fixed-delay modes
    - Uses asyncio.Lock for thread-safe rate limiting
    - Prevents overwhelming target servers
```

#### CrawlerService
```python
class CrawlerService:
    Main crawler orchestration:
    - URL queue management (to_visit, visited_urls)
    - Sitemap detection and parsing
    - URL discovery from HTML links
    - Page data extraction
    - Image downloading
    - File output management
    - Concurrent crawling with semaphores
```

**Key Methods**:

| Method | Purpose |
|--------|---------|
| `crawl()` | Main entry point, orchestrates entire crawl process |
| `is_sitemap()` | Detects if URL is a sitemap XML file |
| `parse_sitemap()` | Recursively parses sitemap files |
| `discover_urls()` | Extracts internal links from HTML |
| `extract_page_data()` | Scrapes data from a single page |
| `download_image()` | Downloads images asynchronously |
| `save_page_data()` | Writes JSON and Markdown files |

## Data Flow

### 1. Job Submission Flow

```
Client → POST /crawl
    ↓
Validate CrawlConfig (Pydantic)
    ↓
Generate job_id (UUID)
    ↓
Create CrawlStatus (status: pending)
    ↓
Add background task
    ↓
Return job_id immediately
    ↓
Background: run_crawl_job() starts
```

### 2. Crawl Execution Flow

```
run_crawl_job(job_id, config)
    ↓
Create CrawlerService instance
    ↓
Setup output directories
    ↓
Check if URL is sitemap
    ├─ Yes: Parse sitemap → Extract all URLs
    └─ No: Add URL to queue
    ↓
Initialize AsyncWebCrawler (Playwright)
    ↓
┌─────────── Crawl Loop ───────────┐
│  While to_visit AND pages < max  │
│      ↓                            │
│  Batch URLs (concurrency limit)  │
│      ↓                            │
│  For each URL in batch:          │
│      • Rate limit                │
│      • Fetch with Playwright     │
│      • Extract data              │
│      • Download images           │
│      • Save JSON + Markdown      │
│      • Discover new URLs (if enabled)
│      ↓                            │
│  Update visited_urls             │
│      ↓                            │
└───────── Repeat ─────────────────┘
    ↓
Update job status to completed
    ↓
Return result
```

### 3. Status Check Flow

```
Client → GET /status/{job_id}
    ↓
Lookup job_id in jobs dict
    ├─ Found: Return CrawlStatus
    └─ Not Found: Return 404
```

## Concurrency Model

The service uses Python's asyncio for concurrency:

### API Level
- FastAPI runs on uvicorn (ASGI server)
- Each request handled asynchronously
- Background tasks run concurrently with request handling
- No thread blocking

### Crawler Level
- `asyncio.Semaphore` limits parallel requests to `max_concurrency`
- `asyncio.gather()` processes URL batches concurrently
- `RateLimiter` uses `asyncio.Lock` for thread-safe throttling
- All I/O operations are async (aiohttp, aiofiles)

### Example Concurrency Flow

```python
# max_concurrency = 4
Semaphore(4) → Only 4 requests can be active simultaneously

Batch 1: [URL1, URL2, URL3, URL4] → All start immediately
    ↓ (URL1 completes)
Batch 2: [URL5] → Starts when slot available
    ↓ (URL2, URL3 complete)
Batch 2: [URL6, URL7] → Start in freed slots
    ↓ (All complete)
Next batch...
```

## Design Patterns

### 1. Service Pattern
`CrawlerService` encapsulates all crawling logic, keeping it separate from API concerns.

### 2. Builder Pattern
`CrawlConfig` acts as a builder for crawler configuration with sensible defaults.

### 3. Strategy Pattern
Rate limiting strategy can be RPM-based or fixed-delay, selected via configuration.

### 4. Observer Pattern (Implicit)
Jobs can be monitored via polling the `/status/{job_id}` endpoint.

### 5. Producer-Consumer Pattern
- API produces jobs (adds to queue)
- Background tasks consume jobs (process from queue)

## Technology Stack

### Core Framework
- **FastAPI**: Modern async web framework with automatic API documentation
- **Uvicorn**: ASGI server for running FastAPI
- **Pydantic**: Data validation and serialization

### Crawling & Scraping
- **crawl4ai**: High-level web crawling library
- **Playwright**: Headless browser automation (renders JavaScript)
- **BeautifulSoup**: HTML parsing and data extraction
- **aiohttp**: Async HTTP client for image downloads

### Async I/O
- **asyncio**: Python's async/await framework
- **aiofiles**: Async file operations

## Storage Architecture

### File System Structure

```
output/
└── {label}/                           # Auto-generated or user-provided
    ├── images/                        # Downloaded images
    │   ├── image_001.jpg
    │   ├── image_002.png
    │   └── ...
    ├── data_00001.json               # Page metadata
    ├── site_00001.md                 # Page content (markdown)
    ├── data_00002.json
    ├── site_00002.md
    └── ...
```

### Naming Conventions
- Labels: `{domain}_{timestamp}` (e.g., `example_com_20250321_143022`)
- Data files: `data_{number:05d}.json` (e.g., `data_00001.json`)
- Markdown files: `site_{number:05d}.md` (e.g., `site_00001.md`)
- Images: Original filename or `image_{hash}.jpg`

### Data Format

**JSON (data_XXXXX.json)**:
```json
{
  "title": ["Page Title"],
  "page_url": ["https://example.com/page"],
  "meta_img_url": ["https://example.com/og-image.jpg"],
  "images": ["https://example.com/img1.jpg"],
  "date": ["2025-03-21"]
}
```

**Markdown (site_XXXXX.md)**:
- Clean markdown content extracted from HTML
- Headings, paragraphs, lists, links preserved
- Code blocks, tables formatted
- External styling and scripts removed

## Scalability Considerations

### Current Limitations
1. **In-Memory Job Storage**: Jobs lost on restart
2. **Single Instance**: No distributed crawling
3. **No Job Persistence**: Can't resume failed jobs
4. **No Result Caching**: Re-crawls duplicate URLs

### Scaling Options

#### Horizontal Scaling
```
Load Balancer (Nginx)
    ↓
┌─────────┬─────────┬─────────┐
│ API 1   │ API 2   │ API 3   │
└─────────┴─────────┴─────────┘
    ↓
Shared job store (queue & status)
    ↓
┌─────────┬─────────┬─────────┐
│Worker 1 │Worker 2 │Worker 3 │
└─────────┴─────────┴─────────┘
    ↓
Shared Storage (S3, NFS)
```

#### Vertical Scaling
- Increase `max_concurrency` (requires more CPU/memory)
- Use more uvicorn workers
- Optimize Playwright browser instances

### Future Improvements

1. **Job Persistence**
   - Store jobs in a database
   - Resume interrupted crawls
   - Job history and analytics

2. **Distributed Crawling**
   - Task queue for distributed crawling
   - Shared coordination store
   - Multiple worker nodes

3. **Result Caching**
   - Cache crawled pages
   - ETags for change detection
   - Incremental crawls

4. **Enhanced Monitoring**
   - Prometheus metrics
   - Grafana dashboards
   - Real-time progress updates via WebSockets

## Security Architecture

### Current Security Measures
1. **Input Validation**: Pydantic validates all inputs
2. **URL Validation**: Only HTTP/HTTPS URLs accepted
3. **Concurrency Limits**: Max 20 concurrent requests
4. **Rate Limiting**: Prevents DoS on target sites
5. **CORS**: Configurable cross-origin policies

### Security Recommendations
1. **Add Authentication**: API keys or OAuth2
2. **Request Rate Limiting**: Limit API calls per client
3. **Output Directory Restrictions**: Prevent path traversal
4. **Content Security**: Scan downloaded content for malware
5. **HTTPS Only**: Enforce HTTPS in production
6. **Resource Limits**: Memory and disk quotas per job

## Error Handling

### Levels of Error Handling

1. **API Level** (FastAPI)
   - Validation errors (422)
   - Not found errors (404)
   - Generic exceptions (500)

2. **Crawler Level** (CrawlerService)
   - Network errors (retry, skip)
   - Parsing errors (log, skip)
   - Download errors (continue)

3. **Job Level** (run_crawl_job)
   - Caught exceptions update job status to "failed"
   - Error messages stored in job status

### Error Recovery Strategy

```python
try:
    crawl page
except NetworkError:
    log error, skip page, continue
except ParsingError:
    log error, skip page, continue
except CriticalError:
    mark job as failed, stop crawling
```

## Performance Characteristics

### Resource Usage

| Resource | Usage Pattern |
|----------|---------------|
| CPU | Moderate (HTML parsing, image processing) |
| Memory | Grows with concurrency and page size |
| Disk I/O | High (writing files, downloading images) |
| Network | High (fetching pages, downloading images) |

### Bottlenecks

1. **Rate Limiting**: Intentional slowdown to respect target servers
2. **Playwright Startup**: Browser initialization takes time
3. **Image Downloads**: Can be slow for large images
4. **File I/O**: Writing many small files

### Optimization Strategies

1. **Skip images** when not needed
2. **Increase concurrency** for faster crawling
3. **Use sitemaps** for direct URL access
4. **Batch file writes** to reduce I/O
5. **Reuse browser instances** (already implemented)

## Testing Strategy

### Unit Tests
- Models validation
- URL normalization
- Sitemap parsing
- Rate limiter logic

### Integration Tests
- API endpoints
- Full crawl workflows
- Error scenarios

### Performance Tests
- Concurrent job handling
- Large sitemap processing
- Memory usage under load

---

## Conclusion

The Crawl4AI FastAPI service is designed as a modular, async-first web crawling system with clear separation of concerns. It balances performance with courtesy through configurable rate limiting, handles various crawling modes (sitemap, discovery), and provides a simple REST API for job management.

The architecture is suitable for small to medium-scale crawling tasks and can be extended with job persistence, distributed processing, and enhanced monitoring for larger deployments.

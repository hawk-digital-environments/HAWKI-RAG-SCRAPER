# API Reference

Complete reference for the crawler API and the SvelteKit UI proxy endpoints.

## Base URLs

| Surface | Default URL | Notes |
|---------|-------------|-------|
| SvelteKit UI | `http://localhost:5173` | Started with `make start-ui` or `npm --prefix ui run dev`. |
| UI API routes | Same origin as UI, `/api/...` | Browser-facing routes used by `ui/src/lib/api/index.ts`. |
| Crawler API | `http://localhost:8040`, fallback `http://localhost:8000` | Configured with `CRAWLER_API_BASE_URL`. |
| RabbitMQ management API | `http://localhost:15672/api` | Configured with `RABBITMQ_MGMT_API_URL`. |

For production, replace these with the deployment domains or set the environment variables described below.

## Authentication

Currently, the API does not require authentication. For production deployments, consider adding API key authentication or OAuth2.

The UI server authenticates to RabbitMQ management with `RABBITMQ_MGMT_USER` and `RABBITMQ_MGMT_PASSWORD`.

## SvelteKit UI API Routes

The frontend does not call the crawler and RabbitMQ services directly by default. Production UI pages and components call `ui/src/lib/api/index.ts`, and that client calls these SvelteKit API routes.

### UI Environment Variables

| Variable | Default | Responsibility |
|----------|---------|----------------|
| `PUBLIC_API_BASE_URL` | empty | Optional browser-visible API base. Leave empty for same-origin `/api/...`. |
| `CRAWLER_API_BASE_URL` | `http://localhost:8040,http://localhost:8000` fallback list | Backend crawler API base URL(s). Comma-separated values are supported. |
| `RABBITMQ_MGMT_API_URL` | `http://localhost:15672/api` | RabbitMQ management API base URL. |
| `RABBITMQ_MGMT_USER` | `guest` | RabbitMQ management user. |
| `RABBITMQ_MGMT_PASSWORD` | `guest` | RabbitMQ management password. |
| `PROFILES_HOST_DIR` | `../profiles` from `ui/` | Host path for editable profile JSON files. |
| `PROFILES_CONTAINER_DIR` | `/app/profiles` | Container path written into crawl submissions. |

### GET /api/profiles

Lists profile JSON files and `.json.example` templates.

**Response**

```json
{
  "profiles": [
    {
      "name": "hawk",
      "hostPath": "/path/to/profiles/hawk.json",
      "containerPath": "/app/profiles/hawk.json",
      "match_hosts": ["hawk.de", "*.hawk.de"],
      "profile": {},
      "readonlyExample": false
    }
  ]
}
```

### POST /api/profiles

Creates or overwrites a writable profile JSON file.

**Request**

```json
{
  "name": "hawk",
  "profile": {
    "name": "hawk",
    "match_hosts": ["hawk.de"],
    "sitemap": {
      "enabled": true,
      "base_url": "https://www.hawk.de/sitemaps/main/sitemap.xml"
    }
  }
}
```

### GET /api/profiles/[name]

Reads one profile JSON file. If `<name>.json` does not exist, the route attempts `<name>.json.example` and marks it as read-only.

### PUT /api/profiles/[name]

Updates one writable profile JSON file.

**Request**

```json
{
  "profile": {
    "name": "hawk",
    "match_hosts": ["hawk.de"]
  }
}
```

### POST /api/crawler/submit

Proxies a crawl submission to crawler `POST /crawl`.

### GET /api/crawler/jobs

Proxies crawler `GET /jobs`.

### POST /api/crawler/job/[jobId]/cancel

Proxies crawler job cancellation to `POST /jobs/{jobId}/cancel`.

### GET /api/crawler/job/[jobId]/summary

Reads crawler output/file metadata and derives URL counters for the UI. The UI can use this for found/completed/missed counts where available.

### GET /api/rabbitmq/queues

Proxies RabbitMQ management queue state and normalizes it for UI display.

**Response**

```json
{
  "queues": [
    {
      "name": "rag_ingestion_jobs",
      "vhost": "/",
      "state": "running",
      "messages": 12,
      "messages_ready": 10,
      "messages_unacknowledged": 2,
      "consumers": 1
    }
  ]
}
```

## UI Client Data Models

`ui/src/lib/api/index.ts` maps backend responses into `ui/src/lib/api/types.ts`.

| UI type | Responsibility |
|---------|----------------|
| `Profile` | Display and edit crawler profile data. Profile ids map to profile file names. |
| `Task` | UI task abstraction. Current backend has no persistent task API, so tasks are derived from profiles. |
| `Job` | UI job abstraction mapped from crawler job status payloads. |
| `Queue` | UI queue abstraction mapped from RabbitMQ management payloads. |

## Common Response Codes

| Code | Description |
|------|-------------|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request - Invalid parameters |
| 404 | Not Found - Resource doesn't exist |
| 422 | Validation Error - Invalid request body |
| 500 | Internal Server Error |

---

## Endpoints

### GET /

Get API information and available endpoints.

**Response**

```json
{
  "message": "Crawl4AI API is running",
  "version": "1.0.0",
  "endpoints": {
    "/crawl": "POST - Submit a crawl job",
    "/status/{job_id}": "GET - Check crawl job status",
    "/jobs": "GET - List all jobs",
    "/docs": "GET - API documentation"
  }
}
```

---

### POST /crawl

Submit a new crawl job for processing.

**Request Body**

```json
{
  "url": "https://example.com",
  "max_pages": 100,
  "output_dir": "output",
  "label": "my_crawl_job",
  "skip_images": false,
  "image_exceptions": ".header img, .footer img",
  "date_selector": "time, .date, meta[property='og:updated_time']",
  "max_concurrency": 4,
  "max_rpm": 60,
  "request_delay": null,
  "discovery_mode": false
}
```

**Parameters**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string (URL) | Yes | - | The starting URL to crawl. Must be a valid HTTP/HTTPS URL |
| `max_pages` | integer | No | 100 | Maximum number of pages to crawl. Range: 1-∞ |
| `output_dir` | string | No | "output" | Base directory for storing crawled data |
| `label` | string | No | auto-generated | Label for this crawl job. Auto-generated format: `{domain}_{timestamp}` |
| `skip_images` | boolean | No | false | Whether to skip downloading images |
| `image_exceptions` | string | No | null | Comma-separated CSS selectors for elements to exclude from image scraping |
| `date_selector` | string | No | null | CSS selector for date elements to extract |
| `max_concurrency` | integer | No | 4 | Maximum number of parallel requests. Range: 1-20 |
| `max_rpm` | integer | No | 60 | Maximum requests per minute. Range: 1-∞ |
| `request_delay` | integer | No | null | Fixed delay between requests in milliseconds. Overrides `max_rpm` |
| `discovery_mode` | boolean | No | false | Enable URL discovery mode to crawl linked pages |

**Response** (200 OK)

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Crawl job submitted successfully",
  "status": "pending"
}
```

**Example cURL**

```bash
curl -X POST "http://localhost:8000/crawl" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "max_pages": 50,
    "discovery_mode": true,
    "skip_images": true,
    "max_rpm": 30
  }'
```

**Example Python**

```python
import requests

config = {
    "url": "https://example.com",
    "max_pages": 50,
    "discovery_mode": True,
    "skip_images": True,
    "max_rpm": 30
}

response = requests.post("http://localhost:8000/crawl", json=config)
job = response.json()
print(f"Job ID: {job['job_id']}")
```

**Validation Errors**

```json
{
  "detail": [
    {
      "loc": ["body", "url"],
      "msg": "invalid or missing URL scheme",
      "type": "value_error.url.scheme"
    }
  ]
}
```

---

### GET /status/{job_id}

Get the current status of a crawl job.

**Path Parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `job_id` | string (UUID) | Yes | The unique identifier of the crawl job |

**Response** (200 OK)

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "message": "Crawl completed successfully",
  "pages_crawled": 45,
  "total_pages": 45,
  "output_directory": "output/example_com_20250321_143022",
  "started_at": "2025-03-21T14:30:22.123456",
  "completed_at": "2025-03-21T14:35:18.654321"
}
```

**Status Field Values**

| Status | Description |
|--------|-------------|
| `pending` | Job is waiting to start |
| `running` | Job is currently crawling |
| `completed` | Job finished successfully |
| `failed` | Job encountered an error |

**Response** (404 Not Found)

```json
{
  "detail": "Job not found"
}
```

**Example cURL**

```bash
curl -X GET "http://localhost:8000/status/550e8400-e29b-41d4-a716-446655440000"
```

**Example Python**

```python
import requests

job_id = "550e8400-e29b-41d4-a716-446655440000"
response = requests.get(f"http://localhost:8000/status/{job_id}")
status = response.json()

print(f"Status: {status['status']}")
print(f"Pages crawled: {status['pages_crawled']}")
```

---

### GET /jobs

List all crawl jobs in the system.

**Response** (200 OK)

```json
{
  "total_jobs": 2,
  "jobs": {
    "550e8400-e29b-41d4-a716-446655440000": {
      "job_id": "550e8400-e29b-41d4-a716-446655440000",
      "status": "completed",
      "message": "Crawl completed successfully",
      "pages_crawled": 45,
      "total_pages": 45,
      "output_directory": "output/example_com_20250321_143022",
      "started_at": "2025-03-21T14:30:22.123456",
      "completed_at": "2025-03-21T14:35:18.654321"
    },
    "660f9500-f39c-52e5-b827-557766551111": {
      "job_id": "660f9500-f39c-52e5-b827-557766551111",
      "status": "running",
      "message": "Crawling in progress...",
      "pages_crawled": 12,
      "total_pages": 0,
      "output_directory": null,
      "started_at": "2025-03-21T14:40:10.987654",
      "completed_at": null
    }
  }
}
```

**Example cURL**

```bash
curl -X GET "http://localhost:8000/jobs"
```

**Example Python**

```python
import requests

response = requests.get("http://localhost:8000/jobs")
jobs = response.json()

print(f"Total jobs: {jobs['total_jobs']}")
for job_id, job_info in jobs['jobs'].items():
    print(f"{job_id}: {job_info['status']}")
```

---

### DELETE /jobs/{job_id}

Delete a job from the jobs list. Note: This only removes the job record, not the crawled data.

**Path Parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `job_id` | string (UUID) | Yes | The unique identifier of the crawl job to delete |

**Response** (200 OK)

```json
{
  "message": "Job 550e8400-e29b-41d4-a716-446655440000 deleted successfully"
}
```

**Response** (404 Not Found)

```json
{
  "detail": "Job not found"
}
```

**Example cURL**

```bash
curl -X DELETE "http://localhost:8000/jobs/550e8400-e29b-41d4-a716-446655440000"
```

**Example Python**

```python
import requests

job_id = "550e8400-e29b-41d4-a716-446655440000"
response = requests.delete(f"http://localhost:8000/jobs/{job_id}")
result = response.json()
print(result['message'])
```

---

### GET /health

Health check endpoint for monitoring and load balancers.

**Response** (200 OK)

```json
{
  "status": "healthy",
  "timestamp": "2025-03-21T14:30:22.123456"
}
```

**Example cURL**

```bash
curl -X GET "http://localhost:8000/health"
```

---

## Data Models

### CrawlConfig

Configuration model for crawl jobs.

```python
{
  "url": str,                    # Required, must be valid HTTP/HTTPS URL
  "max_pages": int,              # Optional, default: 100, min: 1
  "output_dir": str,             # Optional, default: "output"
  "label": str | None,           # Optional, auto-generated if null
  "skip_images": bool,           # Optional, default: false
  "image_exceptions": str | None, # Optional, comma-separated CSS selectors
  "date_selector": str | None,   # Optional, CSS selector
  "max_concurrency": int,        # Optional, default: 4, range: 1-20
  "max_rpm": int,                # Optional, default: 60, min: 1
  "request_delay": int | None,   # Optional, in milliseconds
  "discovery_mode": bool         # Optional, default: false
}
```

### CrawlStatus

Status information for a crawl job.

```python
{
  "job_id": str,                 # UUID of the job
  "status": str,                 # "pending" | "running" | "completed" | "failed"
  "message": str,                # Human-readable status message
  "pages_crawled": int,          # Number of pages successfully crawled
  "total_pages": int,            # Total pages to crawl (may be 0 if unknown)
  "output_directory": str | None, # Path to output directory
  "started_at": datetime,        # ISO 8601 timestamp
  "completed_at": datetime | None # ISO 8601 timestamp or null if not completed
}
```

### PageData

Data structure for a single crawled page (saved in JSON files).

```python
{
  "title": List[str],            # Page titles found
  "page_url": List[str],         # The crawled URL
  "meta_img_url": List[str],     # Open Graph image URLs
  "images": List[str],           # Image URLs found on the page
  "date": List[str]              # Dates extracted using date_selector
}
```

---

## Interactive Documentation

The API provides interactive documentation using Swagger UI and ReDoc:

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **OpenAPI JSON**: `http://localhost:8000/openapi.json`

These interfaces allow you to:
- Explore all endpoints
- Test API calls directly from the browser
- View request/response schemas
- Download OpenAPI specification

---

## Rate Limiting

The API itself does not implement rate limiting for incoming requests. However, the crawler implements rate limiting for outgoing requests to target websites:

- **RPM-based**: Controlled by `max_rpm` parameter
- **Fixed delay**: Controlled by `request_delay` parameter (overrides RPM)

For API-level rate limiting in production, use a reverse proxy like Nginx with rate limiting modules.

---

## Error Handling

### Validation Errors (422)

Returned when request body fails validation:

```json
{
  "detail": [
    {
      "loc": ["body", "max_concurrency"],
      "msg": "ensure this value is less than or equal to 20",
      "type": "value_error.number.not_le"
    }
  ]
}
```

### Not Found Errors (404)

Returned when a resource doesn't exist:

```json
{
  "detail": "Job not found"
}
```

### Server Errors (500)

Returned when an unexpected error occurs:

```json
{
  "detail": "Internal server error"
}
```

---

## Best Practices

1. **Always check job status**: Poll the `/status/{job_id}` endpoint to monitor progress
2. **Use appropriate rate limits**: Set `max_rpm` and `request_delay` based on target website tolerance
3. **Handle errors gracefully**: Check response status codes and handle 404/422/500 errors
4. **Store job IDs**: Save job IDs to retrieve results later
5. **Clean up old jobs**: Use DELETE endpoint to remove completed jobs from memory
6. **Use discovery mode wisely**: Discovery mode can lead to crawling many more pages than expected
7. **Set reasonable max_pages**: Start with small values and increase based on needs

---

## Webhooks (Future Feature)

Currently, the API does not support webhooks. To monitor job completion:

1. Poll `/status/{job_id}` endpoint
2. Implement your own webhook service that polls the API
3. Watch the output directory for new files

Future versions may include webhook support for job completion notifications.

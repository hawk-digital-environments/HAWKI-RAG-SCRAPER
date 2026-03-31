# Service Layer Architecture

This document explains the service layer architecture of the crawler project.

## Overview

The crawler includes a clean, maintainable service layer with five core components:

1. **JobStateManager** - Persistent job state tracking
2. **StorageManager** - Centralized file I/O operations
3. **URLTrackingManager** - URL discovery and tracking with dates
4. **ProgressTracker** - Rate-limited progress broadcasting
5. **SummaryManager** - Job summary creation and export

These services are **completely optional** and the crawler maintains full backwards compatibility with the original implementation.

## Architecture

```
/services/
  ├── __init__.py                  # Package exports
  ├── job_state_manager.py         # Persistent state tracking
  ├── storage_manager.py           # File I/O operations
  ├── url_tracking_manager.py      # URL tracking with dates
  ├── progress_tracker.py          # Rate-limited progress updates
  └── summary_manager.py           # Summary generation

/app/shared/{job_id}/              # Active Docker storage structure
  ├── job_state.json               # Job metadata and status
  ├── urls_tracking.json           # URL tracking with dates
  ├── summary.json                 # Final job summary
  ├── page_00001/
  │   ├── data_00001.json          # Page metadata
  │   ├── content_00001.md         # Extracted content
  │   └── images/                  # Downloaded images
  └── page_00002/
      └── ...
```

## Service Components

### 1. JobStateManager

**Purpose**: Maintains persistent job state that survives container restarts.

**State File** (`job_state.json`):
```json
{
  "job_id": "77b5f466-0c94-4a1a-86b4-b063112c5ec4",
  "status": "completed",
  "total_urls": 18,
  "completed_urls": 18,
  "failed_urls": 0,
  "started_at": "2025-11-21T17:32:43.539040Z",
  "updated_at": "2025-11-21T17:32:51.477731Z",
  "completed_at": "2025-11-21T17:32:51.477731Z",
  "current_url": "https://www.hawki.info/roadmap",
  "output_directory": "/app/shared/{job_id}",
  "error": null
}
```

**Use Case**: Laravel or other clients can read this file to monitor job progress without external message queues.

### 2. StorageManager

**Purpose**: Centralizes all file I/O operations with security and consistency.

**Features**:
- Automatic directory creation
- Path security validation (prevents directory traversal)
- File metadata extraction
- Consistent file organization

**Directory Structure**:
- All files stored in `/app/shared/{job_id}/`
- Each page in separate folder: `page_00001/`, `page_00002/`, etc.
- Images in subfolder: `page_00001/images/`
- Job state at root: `job_state.json`

## New API Endpoints

### GET /jobs/{job_id}/files

List all files for a specific job.

**Response**:
```json
{
  "job_id": "77b5f466-0c94-4a1a-86b4-b063112c5ec4",
  "total_files": 25,
  "files": [
    {
      "name": "job_state.json",
      "path": "job_state.json",
      "size": 429,
      "modified": 1763746371.463791,
      "type": "application/json"
    },
    {
      "name": "content.md",
      "path": "page_00001/content.md",
      "size": 17313,
      "modified": 1763746371.395678,
      "type": "text/markdown"
    }
  ]
}
```

**Use Case**: Laravel discovers what files were scraped for a job.

### GET /jobs/{job_id}/files/{file_path}

Download a specific file from a job.

**Example**:
```bash
curl http://localhost:8004/jobs/77b5f466-0c94-4a1a-86b4-b063112c5ec4/files/page_00001/content.md
```

**Response**: File content with appropriate Content-Type header.

**Use Case**: Laravel retrieves scraped content, images, or metadata.

## Integration with Existing Code

The service layer integrates seamlessly **without changing existing business logic**:

### CrawlerService

The crawler constructor now accepts optional service components:

```python
crawler = CrawlerService(
    config,
    job_id=job_id,                          # Optional: unique job ID
    event_emitter=event_emitter,            # Optional: for real-time events
    job_state_manager=job_state_manager,    # Optional: for state tracking
    storage_manager=storage_manager         # Optional: for file I/O
)
```

**Backwards Compatibility**: If services are not provided (None), the crawler uses the original implementation.

### Event Hooks

Events are emitted at key points without changing business logic:

```python
# Before fetching URL
if self.event_emitter:
    await self.event_emitter.url_fetching(url, page_number, total_pages)

# After scraping succeeds
if self.event_emitter:
    await self.event_emitter.url_scraped(url, page_number, success=True)
```

### State Updates

State is updated throughout the crawl lifecycle:

```python
# Set current URL being processed
if self.job_state_manager:
    await self.job_state_manager.set_current_url(url)

# Increment completed count
if self.job_state_manager:
    await self.job_state_manager.increment_completed()
```

## Environment Variables

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `DATA_PATH` | Base path for job storage | `/app/shared` | `/app/shared` |

**Configure in docker-compose.yml**:
```yaml
environment:
  - DATA_PATH=${DATA_PATH:-/app/shared}
```

**Or in .env file**:
```bash
DATA_PATH=/app/shared
```

## Usage Examples

### Basic Usage (Backwards Compatible)

The crawler works exactly as before without any services:

```bash
curl -X POST http://localhost:8004/crawl \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://example.com",
    "max_pages": 10
  }'
```

Data is still saved to `./output/{label}/` as before.

### With Services (New Architecture)

When running in the Docker container, services are automatically initialized and data is saved to `/app/shared/{job_id}/`:

```bash
# 1. Submit job
curl -X POST http://localhost:8004/crawl \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com", "max_pages": 10}'

# Response: {"job_id": "abc-123", ...}

# 2. Monitor state (via file system or API)
curl http://localhost:8004/jobs/abc-123/files/job_state.json

# 3. List all files
curl http://localhost:8004/jobs/abc-123/files

# 4. Download specific file
curl http://localhost:8004/jobs/abc-123/files/page_00001/content.md
```

### Laravel Integration

```php
// Submit crawl job
$response = Http::post('http://crawler:8004/crawl', [
    'url' => 'https://example.com/sitemap.xml',
    'max_pages' => 100
]);

$jobId = $response->json('job_id');

// Poll for completion
$status = Http::get("http://crawler:8004/status/{$jobId}")->json();

// Or read state file directly from shared volume
$state = json_decode(
    file_get_contents("/app/shared/{$jobId}/job_state.json")
);

// List all files
$files = Http::get("http://crawler:8004/jobs/{$jobId}/files")->json();

// Download specific file
$content = Http::get("http://crawler:8004/jobs/{$jobId}/files/page_00001/content.md")->body();
```

## Testing

### Test State Persistence

```bash
# Submit job
JOB_ID=$(curl -X POST http://localhost:8004/crawl \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com", "max_pages": 1}' | jq -r '.job_id')

# Wait for completion
sleep 10

# Check state file
cat /app/shared/${JOB_ID}/job_state.json | jq
```

### Test File Endpoints

```bash
# List files
curl http://localhost:8004/jobs/${JOB_ID}/files | jq

# Download file
curl http://localhost:8004/jobs/${JOB_ID}/files/page_00001/content.md
```

## Design Principles

### 1. Separation of Concerns

Each service has a single, well-defined responsibility:
- **JobStateManager**: State tracking
- **StorageManager**: File I/O
- **URLTrackingManager**: URL discovery and date tracking
- **ProgressTracker**: Rate-limited progress updates
- **SummaryManager**: Summary generation and export

### 2. No Business Logic Changes

Services integrate through hooks without modifying the scraping flow:
- Original logic remains intact
- Services are checked with `if self.service:`
- Failures in services don't break the crawler

### 3. Optional and Backwards Compatible

- Services can be None (original behavior)
- Old output structure (`./output/`) still supported
- No breaking changes to API

### 4. Testable and Maintainable

- Each service is independently testable
- Clear interfaces and documentation
- Type hints for better IDE support

## Troubleshooting

### State File Not Updating

**Symptom**: `job_state.json` is stale or missing

**Solutions**:
1. Check `/app/shared` storage is mounted
2. Verify write permissions on volume
3. Check logs for "Failed to write job state" warnings

### Files Not Accessible

**Symptom**: 404 errors when downloading files

**Solutions**:
1. Verify job completed successfully
2. Check job_id is correct
3. Ensure `/app/shared` storage is properly mounted
4. Check file path doesn't have traversal attempts

## Future Enhancements

Potential additions that maintain the same architecture:

1. **Job Resumption**: Resume interrupted crawl jobs from URL tracking state
2. **File Compression**: Automatic ZIP creation for completed jobs
3. **Cloud Storage**: Pluggable storage backends (S3, Azure, etc.)
4. **Retry Logic**: Automatic retry for failed URLs with exponential backoff
5. **Rate Limit Adaptation**: Dynamic rate limiting based on server responses
6. **Content Deduplication**: Skip URLs with unchanged content hash

All enhancements would follow the same pattern:
- Create new service class
- Add optional integration in crawler
- Maintain backwards compatibility
- Document clearly

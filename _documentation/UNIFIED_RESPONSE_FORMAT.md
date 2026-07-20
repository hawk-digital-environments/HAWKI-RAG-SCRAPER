# Unified Response Format

## Overview

Both the `/crawl` endpoint response and WebSocket events now use the same consistent structure, making it easier to handle responses with a single parser/handler.

## Structure

All responses follow this format:

```json
{
  "job_id": "unique-job-id",
  "event": "event_type",
  "data": {
    // Event-specific data
  },
  "timestamp": "2025-11-24T11:55:23.046721Z"
}
```

## Fields

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | string | Unique identifier for the job |
| `event` | string | Type of event (e.g., "job_submitted", "url_scraped") |
| `data` | object | Event-specific data |
| `timestamp` | string | ISO-8601 UTC timestamp |

## Examples

### 1. POST /crawl Response

**Request**:
```bash
curl -X POST http://localhost:8004/crawl \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://example.com",
    "max_pages": 10
  }'
```

**Response**:
```json
{
  "job_id": "a5338c8f-9605-4e5f-8ed5-6757e5770fa0",
  "event": "job_submitted",
  "data": {
    "status": "pending",
    "message": "Crawl job submitted successfully"
  },
  "timestamp": "2025-11-24T11:55:23.046721Z"
}
```

### 2. WebSocket Event: sitemap_detected

```json
{
  "job_id": "a5338c8f-9605-4e5f-8ed5-6757e5770fa0",
  "event": "sitemap_detected",
  "data": {
    "sitemap_url": "https://example.com/sitemap.xml",
    "total_urls": 150
  },
  "timestamp": "2025-11-24T11:55:25.123456Z"
}
```

### 3. WebSocket Event: url_scraped

```json
{
  "job_id": "a5338c8f-9605-4e5f-8ed5-6757e5770fa0",
  "event": "url_scraped",
  "data": {
    "url": "https://example.com/page1",
    "page_number": 1,
    "success": true
  },
  "timestamp": "2025-11-24T11:55:28.789012Z"
}
```

### 4. WebSocket Event: job_completed

```json
{
  "job_id": "a5338c8f-9605-4e5f-8ed5-6757e5770fa0",
  "event": "job_completed",
  "data": {
    "pages_crawled": 10,
    "output_directory": "/var/www/html/shared/a5338c8f-9605-4e5f-8ed5-6757e5770fa0",
    "success": true,
    "error": null
  },
  "timestamp": "2025-11-24T11:56:15.456789Z"
}
```

## Event Types

### Initial Response Events

| Event | Source | Description |
|-------|--------|-------------|
| `job_submitted` | POST /crawl | Job created and queued |

### Progress Events (WebSocket)

| Event | Description |
|-------|-------------|
| `sitemap_detected` | Sitemap URL discovered |
| `urls_discovered` | URLs extracted from sitemap |
| `crawling_started` | Crawling process began |
| `url_fetching` | Starting to fetch a URL |
| `url_scraped` | URL scraping completed (success/fail) |
| `url_completed` | URL processing finished, files saved |
| `job_completed` | Entire job finished (success/fail) |

## Unified Handler Example

### JavaScript/TypeScript

```typescript
interface CrawlEvent {
  job_id: string;
  event: string;
  data: any;
  timestamp: string;
}

class CrawlEventHandler {
  handleEvent(event: CrawlEvent) {
    console.log(`[${event.timestamp}] ${event.event}:`, event.data);

    switch (event.event) {
      case 'job_submitted':
        this.onJobSubmitted(event);
        break;
      case 'sitemap_detected':
        this.onSitemapDetected(event);
        break;
      case 'url_scraped':
        this.onUrlScraped(event);
        break;
      case 'job_completed':
        this.onJobCompleted(event);
        break;
      default:
        this.onUnknownEvent(event);
    }
  }

  onJobSubmitted(event: CrawlEvent) {
    const { status, message } = event.data;
    console.log(`Job ${event.job_id} submitted: ${message}`);
  }

  onSitemapDetected(event: CrawlEvent) {
    const { sitemap_url, total_urls } = event.data;
    console.log(`Found sitemap with ${total_urls} URLs`);
  }

  onUrlScraped(event: CrawlEvent) {
    const { url, page_number, success } = event.data;
    if (success) {
      console.log(`✓ Scraped page ${page_number}: ${url}`);
    } else {
      console.error(`✗ Failed page ${page_number}: ${url}`);
    }
  }

  onJobCompleted(event: CrawlEvent) {
    const { pages_crawled, success, error } = event.data;
    if (success) {
      console.log(`✓ Job completed: ${pages_crawled} pages`);
    } else {
      console.error(`✗ Job failed: ${error}`);
    }
  }

  onUnknownEvent(event: CrawlEvent) {
    console.warn(`Unknown event type: ${event.event}`);
  }
}

// Usage
const handler = new CrawlEventHandler();

// Handle initial POST /crawl response
fetch('http://localhost:8004/crawl', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ url: 'https://example.com' })
})
  .then(res => res.json())
  .then(event => handler.handleEvent(event));

// Handle WebSocket events
const ws = new WebSocket('ws://localhost:6001');
ws.onmessage = (msg) => {
  const event = JSON.parse(msg.data);
  handler.handleEvent(event);
};
```

### Python

```python
from dataclasses import dataclass
from typing import Any, Dict
import json

@dataclass
class CrawlEvent:
    job_id: str
    event: str
    data: Dict[str, Any]
    timestamp: str

class CrawlEventHandler:
    def handle_event(self, event: CrawlEvent):
        print(f"[{event.timestamp}] {event.event}: {event.data}")

        handler = getattr(self, f"on_{event.event}", self.on_unknown_event)
        handler(event)

    def on_job_submitted(self, event: CrawlEvent):
        status = event.data['status']
        message = event.data['message']
        print(f"Job {event.job_id} submitted: {message}")

    def on_sitemap_detected(self, event: CrawlEvent):
        total_urls = event.data['total_urls']
        print(f"Found sitemap with {total_urls} URLs")

    def on_url_scraped(self, event: CrawlEvent):
        url = event.data['url']
        page_number = event.data['page_number']
        success = event.data['success']

        if success:
            print(f"✓ Scraped page {page_number}: {url}")
        else:
            print(f"✗ Failed page {page_number}: {url}")

    def on_job_completed(self, event: CrawlEvent):
        pages_crawled = event.data['pages_crawled']
        success = event.data['success']

        if success:
            print(f"✓ Job completed: {pages_crawled} pages")
        else:
            error = event.data.get('error')
            print(f"✗ Job failed: {error}")

    def on_unknown_event(self, event: CrawlEvent):
        print(f"Unknown event type: {event.event}")

# Usage
handler = CrawlEventHandler()

# Handle initial POST /crawl response
import requests
response = requests.post('http://localhost:8004/crawl', json={
    'url': 'https://example.com'
})
event = CrawlEvent(**response.json())
handler.handle_event(event)

# Handle WebSocket events
import asyncio
import websockets

async def listen_events():
    async with websockets.connect('ws://localhost:6001') as ws:
        async for message in ws:
            event_data = json.loads(message)
            event = CrawlEvent(**event_data)
            handler.handle_event(event)

asyncio.run(listen_events())
```

### PHP/Laravel

```php
<?php

namespace App\Services;

class CrawlEventHandler
{
    public function handleEvent(array $event): void
    {
        $timestamp = $event['timestamp'];
        $eventType = $event['event'];
        $data = $event['data'];

        Log::info("[{$timestamp}] {$eventType}", $data);

        $method = 'on' . str_replace('_', '', ucwords($eventType, '_'));

        if (method_exists($this, $method)) {
            $this->$method($event);
        } else {
            $this->onUnknownEvent($event);
        }
    }

    protected function onJobSubmitted(array $event): void
    {
        $jobId = $event['job_id'];
        $status = $event['data']['status'];
        $message = $event['data']['message'];

        Log::info("Job {$jobId} submitted: {$message}");

        // Store in database
        CrawlJob::create([
            'job_id' => $jobId,
            'status' => $status,
            'submitted_at' => $event['timestamp']
        ]);
    }

    protected function onSitemapDetected(array $event): void
    {
        $totalUrls = $event['data']['total_urls'];
        Log::info("Found sitemap with {$totalUrls} URLs");
    }

    protected function onUrlScraped(array $event): void
    {
        $url = $event['data']['url'];
        $pageNumber = $event['data']['page_number'];
        $success = $event['data']['success'];

        if ($success) {
            Log::info("✓ Scraped page {$pageNumber}: {$url}");
        } else {
            Log::error("✗ Failed page {$pageNumber}: {$url}");
        }
    }

    protected function onJobCompleted(array $event): void
    {
        $jobId = $event['job_id'];
        $pagesCrawled = $event['data']['pages_crawled'];
        $success = $event['data']['success'];

        if ($success) {
            Log::info("✓ Job completed: {$pagesCrawled} pages");

            CrawlJob::where('job_id', $jobId)->update([
                'status' => 'completed',
                'pages_crawled' => $pagesCrawled,
                'completed_at' => now()
            ]);
        } else {
            $error = $event['data']['error'];
            Log::error("✗ Job failed: {$error}");

            CrawlJob::where('job_id', $jobId)->update([
                'status' => 'failed',
                'error_message' => $error,
                'completed_at' => now()
            ]);
        }
    }

    protected function onUnknownEvent(array $event): void
    {
        Log::warning("Unknown event type: {$event['event']}");
    }
}

// Usage
$handler = new CrawlEventHandler();

// Handle POST /crawl response
$response = Http::post('http://crawler:8004/crawl', [
    'url' => 'https://example.com'
]);
$handler->handleEvent($response->json());

// Handle WebSocket events (using Laravel WebSockets)
Broadcast::listen('crawler.events', function ($event) use ($handler) {
    $handler->handleEvent($event);
});
```

## Benefits of Unified Format

### 1. Single Parser
Use one data structure/class for all events:
```typescript
interface CrawlEvent { ... }  // One interface for everything
```

### 2. Consistent Error Handling
```typescript
if (!event.data.success) {
  console.error(`Error: ${event.data.error}`);
}
```

### 3. Easy Logging
```typescript
events.forEach(event => {
  logger.log(`[${event.timestamp}] ${event.event}:`, event.data);
});
```

### 4. Simple State Machine
```typescript
switch (event.event) {
  case 'job_submitted': setState('pending'); break;
  case 'crawling_started': setState('running'); break;
  case 'job_completed': setState('done'); break;
}
```

### 5. Type Safety
```typescript
type CrawlEvent = {
  job_id: string;
  event: 'job_submitted' | 'url_scraped' | 'job_completed' | ...;
  data: any;
  timestamp: string;
};
```

## Migration Guide

If you have existing code using the old format:

### Old Format
```json
{
  "job_id": "...",
  "message": "...",
  "status": "..."
}
```

### New Format
```json
{
  "job_id": "...",
  "event": "job_submitted",
  "data": {
    "status": "...",
    "message": "..."
  },
  "timestamp": "..."
}
```

### Migration
```javascript
// Old code
const { job_id, message, status } = response;

// New code
const { job_id, event, data, timestamp } = response;
const { status, message } = data;

// Or keep compatibility
const status = response.data?.status || response.status;
const message = response.data?.message || response.message;
```

## Best Practices

1. **Always check event type**:
   ```javascript
   if (event.event === 'job_submitted') { ... }
   ```

2. **Handle unknown events gracefully**:
   ```javascript
   default: console.warn(`Unknown event: ${event.event}`);
   ```

3. **Store timestamp for debugging**:
   ```javascript
   events.push({ ...event, receivedAt: Date.now() });
   ```

4. **Validate structure**:
   ```javascript
   if (!event.job_id || !event.event || !event.data) {
     throw new Error('Invalid event structure');
   }
   ```

5. **Use discriminated unions (TypeScript)**:
   ```typescript
   type JobSubmitted = {
     event: 'job_submitted';
     data: { status: string; message: string };
   };

   type UrlScraped = {
     event: 'url_scraped';
     data: { url: string; success: boolean };
   };

   type CrawlEvent = JobSubmitted | UrlScraped | ...;
   ```

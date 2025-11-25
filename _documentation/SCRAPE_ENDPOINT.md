# Quick Scrape Endpoint

## Overview

The `/scrape` endpoint provides temporary, storage-free content extraction from a single URL. Perfect for previewing content, quick data extraction, or when you don't need persistent storage.

## Key Features

✅ **No Storage** - Returns data directly in response (nothing saved to disk)
✅ **Single URL** - Extracts content from one page
✅ **Image URLs Only** - Returns image URLs without downloading files
✅ **Fast Response** - Synchronous operation, returns immediately
✅ **Same Extraction Logic** - Uses the same proven extraction methods as full crawl

## Endpoint Details

**URL**: `POST /scrape`

**Request Body**:
```json
{
  "url": "https://example.com",
  "skip_images": false,
  "extract_date": false,
  "date_selector": "meta[property='article:published_time']"
}
```

**Response**:
```json
{
  "url": "https://example.com",
  "success": true,
  "title": "Example Domain",
  "content": "# Example Domain\nThis domain is for use...",
  "images": [
    "https://example.com/image1.jpg",
    "https://example.com/image2.png"
  ],
  "meta_image": "https://example.com/og-image.jpg",
  "date": "2025-11-21",
  "error": null,
  "extraction_time_seconds": 6.67
}
```

## Request Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string (URL) | Yes | - | The URL to scrape |
| `skip_images` | boolean | No | false | Skip image extraction to speed up response |
| `extract_date` | boolean | No | false | Attempt to extract publication date |
| `date_selector` | string | No | null | CSS selector for date extraction |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `url` | string | The scraped URL (may differ if redirected) |
| `success` | boolean | Whether extraction succeeded |
| `title` | string | Page title from `<title>` tag |
| `content` | string | Extracted content in markdown format |
| `images` | array | List of image URLs found on page |
| `meta_image` | string | OpenGraph meta image URL |
| `date` | string | Extracted date (if `extract_date=true`) |
| `error` | string | Error message if `success=false` |
| `extraction_time_seconds` | float | Time taken to scrape |

## Usage Examples

### Basic Usage

Extract content from a URL:

```bash
curl -X POST http://localhost:8004/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com"}'
```

### Skip Images (Faster)

Extract only text content:

```bash
curl -X POST http://localhost:8004/scrape \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://example.com",
    "skip_images": true
  }'
```

### Extract Date

Extract publication date using CSS selector:

```bash
curl -X POST http://localhost:8004/scrape \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://blog.example.com/article",
    "extract_date": true,
    "date_selector": "meta[property=\"article:published_time\"]"
  }'
```

### Python Example

```python
import requests

response = requests.post('http://localhost:8004/scrape', json={
    'url': 'https://example.com',
    'skip_images': False
})

data = response.json()

if data['success']:
    print(f"Title: {data['title']}")
    print(f"Content: {data['content'][:200]}...")
    print(f"Images: {len(data['images'])} found")
else:
    print(f"Error: {data['error']}")
```

### JavaScript Example

```javascript
fetch('http://localhost:8004/scrape', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    url: 'https://example.com'
  })
})
  .then(res => res.json())
  .then(data => {
    if (data.success) {
      console.log('Title:', data.title);
      console.log('Content length:', data.content.length);
      console.log('Images:', data.images);
    } else {
      console.error('Error:', data.error);
    }
  });
```

### Laravel Example

```php
use Illuminate\Support\Facades\Http;

$response = Http::post('http://crawler:8004/scrape', [
    'url' => 'https://example.com',
    'skip_images' => false
]);

$data = $response->json();

if ($data['success']) {
    $article = Article::create([
        'title' => $data['title'],
        'content' => $data['content'],
        'featured_image' => $data['meta_image'],
        'images' => json_encode($data['images'])
    ]);
}
```

## Comparison with `/crawl`

| Feature | `/scrape` | `/crawl` |
|---------|-----------|----------|
| **Storage** | None (in-memory only) | Persistent (files on disk) |
| **URLs** | Single URL | Multiple URLs / sitemap |
| **Images** | URLs only | Downloaded to disk |
| **Response** | Immediate (sync) | Background job (async) |
| **Use Case** | Preview, quick extraction | Bulk scraping, archival |
| **Events** | None | WebSocket events |
| **State Tracking** | None | job_state.json |

## When to Use `/scrape`

✅ **Use `/scrape` when you need:**
- Quick preview of page content
- One-off data extraction
- Real-time content analysis
- No need to store files
- Immediate response required

❌ **Use `/crawl` instead when you need:**
- Multiple pages / sitemap crawling
- Downloaded images on disk
- Persistent storage
- Background processing
- Progress tracking
- File access later

## Content Extraction

The endpoint uses the same multi-fallback extraction strategy as full crawl:

1. **Primary**: crawl4ai's markdown extraction
2. **Fallback 1**: html2text library
3. **Fallback 2**: BeautifulSoup text extraction

This ensures content is extracted even from complex JavaScript-rendered pages.

## Performance

**Typical Response Times**:
- Simple static page: 2-4 seconds
- JavaScript-heavy site: 5-8 seconds
- Complex SPA: 8-12 seconds

**Optimization Tips**:
- Set `skip_images: true` to reduce extraction time by ~20%
- Cache frequently accessed URLs on your side
- Consider rate limiting on client side

## Error Handling

**Success Response** (`success: true`):
```json
{
  "success": true,
  "title": "Page Title",
  "content": "...",
  ...
}
```

**Error Response** (`success: false`):
```json
{
  "url": "https://example.com",
  "success": false,
  "error": "Failed to crawl https://example.com: Connection timeout",
  "extraction_time_seconds": 30.0,
  "title": null,
  "content": null,
  "images": [],
  "meta_image": null,
  "date": null
}
```

**Common Errors**:
- `Connection timeout` - Site is slow or unreachable
- `HTTP 403/404` - Access denied or page not found
- `JavaScript rendering failed` - Complex SPA that won't render
- `Invalid URL` - Malformed URL provided

## Rate Limiting

The endpoint processes requests synchronously. For high-volume scenarios:

1. **Client-side rate limiting**: Implement delays between requests
2. **Caching**: Cache responses for frequently accessed URLs
3. **Use `/crawl`**: For bulk operations, use the async `/crawl` endpoint

## Security Considerations

- ✅ Only publicly accessible URLs can be scraped
- ✅ Follows robots.txt and respects site policies
- ✅ No server-side request forgery (validated URLs)
- ✅ Images returned as URLs (not downloaded/proxied)
- ⚠️ Consider implementing authentication for production use

## Testing

Test the endpoint:

```bash
# Simple test
curl -X POST http://localhost:8004/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com"}'

# Test with skip_images
curl -X POST http://localhost:8004/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com", "skip_images": true}'

# Test error handling (invalid URL)
curl -X POST http://localhost:8004/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://this-site-does-not-exist-12345.com"}'
```

## Troubleshooting

**Problem**: Slow response times (>15 seconds)

**Solutions**:
- Set `skip_images: true`
- Increase page_timeout in code if needed
- Check if target site is slow
- Consider using `/crawl` for background processing

---

**Problem**: Empty content field

**Solutions**:
- Check if page requires authentication
- Verify page loads correctly in browser
- Some pages may block automated access
- Try different date_selector if extracting dates

---

**Problem**: No images extracted

**Solutions**:
- Verify images exist on page
- Check if images are lazy-loaded
- Some sites use canvas/svg instead of img tags
- Images might be in iframes (not supported)

## API Documentation

Full interactive API documentation available at:
- Swagger UI: `http://localhost:8004/docs`
- ReDoc: `http://localhost:8004/redoc`

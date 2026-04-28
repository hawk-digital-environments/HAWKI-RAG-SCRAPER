# Crawl4AI FastAPI Service

A FastAPI interface for the crawl4ai library that provides intelligent web crawling with sitemap support, URL discovery, rate limiting, and structured data extraction.

## Features

- **Sitemap Support**: Automatically detects and parses XML sitemaps
- **URL Discovery Mode**: Discovers and crawls internal links from pages
- **Rate Limiting**: Configurable request throttling (RPM or custom delay)
- **Image Handling**: Downloads images with selective exclusions via CSS selectors
- **Structured Output**: Generates JSON metadata and Markdown content files
- **Concurrent Crawling**: Parallel request processing with configurable concurrency
- **Date Extraction**: Extract dates using custom CSS selectors

## Pipeline Events (Scrape -> Convert -> Ingest)

The scraper now supports RabbitMQ producer publishing for file discovery events without changing
the existing crawl and storage behavior.

- Event published: `scrape.file.discovered`
- Exchange: `pipeline.events` (durable, direct by default)
- Routing key: `scrape.file.discovered`
- Publish point: after a supported file is fully written to the existing `files/` directory
- No conversion or ingestion is executed from this repo

Environment variables:

```bash
COMMUNICATION_ENABLED=true
COMMUNICATION_METHOD=rabbitmq

RABBITMQ_HOST=rabbitmq
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest
RABBITMQ_VHOST=/
RABBITMQ_HEARTBEAT=30
RABBITMQ_CONNECTION_TIMEOUT=30

RABBITMQ_EVENTS_EXCHANGE=pipeline.events
RABBITMQ_EVENTS_EXCHANGE_TYPE=direct
RABBITMQ_FILE_DISCOVERED_ROUTING_KEY=scrape.file.discovered

RABBITMQ_PUBLISHER_CONFIRMS=true
RABBITMQ_PERSISTENT_MESSAGES=true
RABBITMQ_MANDATORY_PUBLISH=true

JOB_SCHEMA_VERSION=1
JOB_SOURCE=scraper
```

Disabled mode:

- If `COMMUNICATION_ENABLED=false` or `COMMUNICATION_METHOD=none`, crawl behavior is unchanged and no RabbitMQ connection is attempted.
- Optional debug outbox: set `FILE_EVENT_OUTBOX_PATH=/path/to/file_events_outbox.jsonl`.

Supported file-event extensions:

- `pdf`, `doc`, `docx`, `ppt`, `pptx`, `xls`, `xlsx`, `txt`, `csv`, `md`, `html`

## Installation

### Using Virtual Environment

```bash
# Create and activate virtual environment
python3 -m venv env
source env/bin/activate  # On Windows: env\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install playwright browsers (required by crawl4ai)
playwright install
```

### Using Docker

```bash
# Build and start the service
docker compose up -d

# View logs
docker compose logs -f

# Stop the service
docker compose down
```

The service will be available at `http://localhost:8000`. Crawled data will be saved to the `./output` directory on your host machine.

## Quick Start

### Start the Server

```bash
# Development mode
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Production mode
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

The API will be available at `http://localhost:8000`

### API Documentation

Interactive API documentation is available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## API Endpoints

### POST /crawl

Submit a crawl job with configuration.

**Request Body:**

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
  "discovery_mode": true
}
```

**Configuration Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | string | *required* | The starting URL to crawl |
| `max_pages` | integer | 100 | Maximum number of pages to crawl |
| `output_dir` | string | "output" | Directory to store crawled data |
| `label` | string | auto-generated | Label for this crawl job |
| `skip_images` | boolean | false | Skip downloading images |
| `image_exceptions` | string | null | CSS selectors for elements to exclude from image scraping |
| `date_selector` | string | null | CSS selector for date elements |
| `max_concurrency` | integer | 4 | Maximum number of parallel requests (1-20) |
| `max_rpm` | integer | 60 | Maximum requests per minute |
| `request_delay` | integer | null | Delay between requests in milliseconds (overrides RPM) |
| `discovery_mode` | boolean | false | Discover and crawl URLs inside the given page |

**Response:**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Crawl job submitted successfully",
  "status": "pending"
}
```

### GET /status/{job_id}

Check the status of a crawl job.

**Response:**

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

**Status Values:**
- `pending`: Job is waiting to start
- `running`: Job is currently crawling
- `completed`: Job finished successfully
- `failed`: Job encountered an error

### GET /jobs

List all crawl jobs.

### DELETE /jobs/{job_id}

Delete a job from the jobs list.

### GET /health

Health check endpoint.

## Output Structure

Each crawl job now uses one normalized layout for every scraped website:

```
/app/shared/{job_id}/
├── job_state.json
├── summary.json
├── pages/
│   └── a/b/c/d/{url_hash}/
│       ├── content.md
│       ├── data.json
│       ├── images/
│       ├── files/
│       └── diagnostics/
└── url_chunks/
```

Every scraped page produces exactly:
- `content.md` for extracted Markdown content
- `data.json` for normalized metadata

`data.json` includes consistent fields for downstream conversion and ingestion, including:
- `title`, `url`, `canonical_url`
- `timestamps.fetched_at`, `timestamps.published_at`, `timestamps.updated_at`
- `tags`, `images`, `documents`
- `status.content_status` to distinguish `success`, `partial`, `empty`, and `binary`

You can validate a dataset with:

```bash
python3 -m src.scripts.validate_dataset /app/shared/<job_id>
```

## Usage Examples

### Example 1: Crawl a Sitemap

```bash
curl -X POST "http://localhost:8000/crawl" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/sitemap.xml",
    "max_pages": 50,
    "max_concurrency": 5
  }'
```

### Example 2: Discovery Mode with Rate Limiting

```bash
curl -X POST "http://localhost:8000/crawl" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "discovery_mode": true,
    "max_pages": 100,
    "max_rpm": 30,
    "date_selector": "time, .published-date",
    "skip_images": true
  }'
```

### Example 3: Custom Request Delay with Image Exclusions

```bash
curl -X POST "http://localhost:8000/crawl" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "request_delay": 2000,
    "image_exceptions": ".header, .footer, .sidebar",
    "max_concurrency": 2
  }'
```

### Example 4: Check Job Status

```bash
curl -X GET "http://localhost:8000/status/550e8400-e29b-41d4-a716-446655440000"
```

## Python Client Example

```python
import requests
import time

# Submit crawl job
response = requests.post("http://localhost:8000/crawl", json={
    "url": "https://example.com",
    "max_pages": 50,
    "discovery_mode": True,
    "date_selector": "time, .date"
})

job_data = response.json()
job_id = job_data["job_id"]
print(f"Job submitted: {job_id}")

# Poll for status
while True:
    status_response = requests.get(f"http://localhost:8000/status/{job_id}")
    status = status_response.json()

    print(f"Status: {status['status']} - {status['message']}")
    print(f"Pages crawled: {status['pages_crawled']}/{status.get('total_pages', '?')}")

    if status['status'] in ['completed', 'failed']:
        if status['status'] == 'completed':
            print(f"Output directory: {status['output_directory']}")
        break

    time.sleep(5)
```

## Advanced Configuration

### Image Exceptions

The `image_exceptions` parameter accepts comma-separated CSS selectors to exclude specific images:

```json
{
  "image_exceptions": ".header img, .footer img, .ads, #sidebar"
}
```

This will exclude images inside elements matching these selectors.

### Date Extraction

The `date_selector` parameter accepts CSS selectors to extract dates:

```json
{
  "date_selector": "time, .date, .published, meta[property='og:updated_time']"
}
```

The crawler will extract dates from elements matching any of these selectors.

### Rate Limiting

Two modes are available:

1. **RPM-based** (default): Set `max_rpm` to control requests per minute
2. **Fixed delay**: Set `request_delay` in milliseconds to override RPM

```json
{
  "max_rpm": 60,           // Makes 1 request per second
  "request_delay": null
}
```

Or:

```json
{
  "max_rpm": 60,           // Ignored when request_delay is set
  "request_delay": 2000    // 2 second delay between requests
}
```

## Sitemap Handling

The crawler automatically detects sitemaps by:
1. URL contains "sitemap" or ends with ".xml"
2. HTTP Content-Type header contains "xml"

Supported sitemap formats:
- Standard XML sitemaps
- Sitemap index files (nested sitemaps)
- Gzipped sitemaps

## Troubleshooting

### Playwright Installation Issues

If you encounter issues with playwright browsers:

```bash
playwright install chromium
```

### Memory Issues with Large Crawls

For large crawl jobs, consider:
- Reducing `max_concurrency`
- Increasing `request_delay`
- Setting `skip_images: true`

### Permission Errors

Ensure the output directory is writable:

```bash
chmod -R 755 output/
```

## Environment Variables

Create a `.env` file for configuration:

```env
CRAWL4AI_API_TOKEN=your_token_here
MAX_CONCURRENT_TASKS=5
LOG_LEVEL=INFO
```

## Performance Tuning

### Optimizing Crawl Speed

For faster crawling:
- Increase `max_concurrency` (up to 20)
- Increase `max_rpm` for rate limiting
- Set `skip_images: true` if images aren't needed
- Use sitemap URLs when available

### Optimizing for Courtesy

For respectful crawling:
- Set `max_concurrency: 1` or `2`
- Use `request_delay` for fixed delays
- Lower `max_rpm` values (e.g., 10-30)

### Memory Management

For large crawls:
- Process in batches by setting lower `max_pages`
- Run multiple jobs sequentially instead of one large job
- Set `max_concurrency` to 2-4 for memory-intensive sites

## Security Considerations

### Best Practices

1. **Rate Limiting**: Always configure appropriate rate limits to avoid overwhelming target servers
2. **Robots.txt**: Respect robots.txt rules when crawling public websites
3. **Authentication**: Use environment variables for sensitive tokens
4. **Output Directory**: Ensure output directories have proper permissions
5. **Input Validation**: The API validates all input parameters, but always sanitize URLs from user input

### Running in Production

#### Using Docker (Recommended)

Docker is the recommended way to run in production:

```bash
# Create .env file with your configuration
cp .env.example .env

# Edit .env with your settings
nano .env

# Start the service
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f crawler
```

#### Using Systemd

For non-Docker deployments, create a systemd service:

```bash
# Create a dedicated user for running the service
sudo useradd -r -s /bin/false crawler

# Set proper permissions
sudo chown -R crawler:crawler /path/to/crawler
sudo chmod 750 /path/to/crawler

# Create systemd service file
sudo nano /etc/systemd/system/crawler.service
```

Add the following content:

```ini
[Unit]
Description=Crawl4AI FastAPI Service
After=network.target

[Service]
Type=simple
User=crawler
WorkingDirectory=/path/to/crawler
Environment="PATH=/path/to/crawler/env/bin"
ExecStart=/path/to/crawler/env/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable crawler
sudo systemctl start crawler
sudo systemctl status crawler
```

## Docker Configuration

### Environment Variables

Configure the application using environment variables in a `.env` file:

```bash
# Server configuration
HOST=0.0.0.0
PORT=8000

# Performance
MAX_CONCURRENT_TASKS=5

# Optional: API security
CRAWL4AI_API_TOKEN=your_secret_token_here

# Optional: LLM provider keys (for advanced crawl4ai features)
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key
```

### Resource Limits

The docker-compose.yml includes default resource limits:

- **CPU**: 1-2 cores
- **Memory**: 1GB minimum, 2GB maximum

Adjust these in `docker-compose.yml` based on your crawling needs:

```yaml
deploy:
  resources:
    limits:
      cpus: '4'
      memory: 4G
    reservations:
      cpus: '2'
      memory: 2G
```

### Persistent Storage

Crawled data is stored in the `./output` directory, which is mounted as a volume. This ensures your data persists even if the container is recreated.

### Building for Production

To build and optimize the Docker image:

```bash
# Build the image
docker compose build

# Or build with no cache
docker compose build --no-cache

# Tag for registry (optional)
docker tag crawl4ai-fastapi:latest your-registry/crawl4ai-fastapi:v1.0
docker push your-registry/crawl4ai-fastapi:v1.0
```

## Monitoring and Logging

### Docker Logs

When running with Docker, view logs using:

```bash
# Follow logs in real-time
docker compose logs -f crawler

# View last 100 lines
docker compose logs --tail=100 crawler

# Export logs to file
docker compose logs crawler > crawler.log
```

### Local Development Logs

For local development without Docker:

```bash
# Run with log output to both console and file
uvicorn main:app --host 0.0.0.0 --port 8000 2>&1 | tee crawler.log
```

### Systemd Logs

For systemd deployments:

```bash
# View systemd logs
journalctl -u crawler.service -f

# View logs from the last hour
journalctl -u crawler.service --since "1 hour ago"
```

### Health Monitoring

Check the health endpoint to monitor service status:

```bash
# Check health
curl http://localhost:8000/health

# Expected response
{
  "status": "healthy",
  "timestamp": "2025-03-21T14:30:22.123456"
}
```

## FAQ

### Q: Can I crawl JavaScript-heavy sites?
A: Yes! The crawler uses Playwright with a headless browser, which fully renders JavaScript.

### Q: How do I handle sites that require authentication?
A: Currently, authentication must be configured in the crawl4ai library. Extend the `CrawlerService` class to add authentication headers.

### Q: What happens if a crawl job fails midway?
A: Partial results are saved. All successfully crawled pages are stored in the output directory.

### Q: Can I crawl multiple sites simultaneously?
A: Yes! Submit multiple jobs to the API. Each job runs independently in the background.

### Q: How do I limit crawling to specific sections of a site?
A: Use discovery mode with a starting URL in the desired section. The crawler only follows internal links from that point.

### Q: Does the crawler respect robots.txt?
A: The underlying crawl4ai library should respect robots.txt, but you should verify this for your use case.

### Q: How can I extract custom data fields?
A: Modify the `extract_page_data` method in `crawler_service.py` to add custom CSS selectors for your data fields.

### Q: Can I export crawled data to a database?
A: The current implementation saves to files. You can extend the `save_page_data` method to write to a database instead.

## Contributing

Contributions are welcome! Please follow these guidelines:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Setup

```bash
# Clone the repository
git clone <repository-url>
cd crawler

# Create virtual environment
python3 -m venv env
source env/bin/activate

# Install dependencies with dev tools
pip install -r requirements.txt
pip install pytest black pylint

# Run tests
pytest

# Format code
black .

# Lint code
pylint *.py
```

## Documentation

Comprehensive documentation is available in the `_documentation` folder:

- **API Reference**: Detailed endpoint documentation
- **Architecture**: System design and components
- **Deployment Guide**: Production deployment instructions
- **Configuration Guide**: Advanced configuration options
- **Developer Guide**: Contributing and extending the service

## License

MIT

## Support

For issues and questions, please open an issue on the project repository.

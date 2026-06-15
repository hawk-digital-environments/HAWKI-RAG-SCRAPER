# Quick Start Guide

Get the Crawl4AI FastAPI service running and submit a crawl job.

## Choose Your Setup Method

### Option 1: Docker

Docker is the recommended setup for this repo. The compose file uses an external
Docker volume and network, so create them before the first start:

```bash
docker volume create rawki_shared_storage
docker network create hawki-network 2>/dev/null || true

# One-time permission fix for the shared storage volume.
docker run --rm -v rawki_shared_storage:/data alpine chown -R 33:33 /data

docker compose up -d
```

The Docker service is available at:

```bash
export CRAWLER_URL=http://localhost:8041
```

Docker will:

- Build the crawler and UI container.
- Install Playwright browser dependencies.
- Start the API behind the container web server.
- Store crawl job data in the `rawki_shared_storage` Docker volume.

### Option 2: Local Development

```bash
chmod +x start_server.sh
./start_server.sh
```

The script will:

- Install Python dependencies from `pyproject.toml`/`uv.lock`.
- Install Playwright's Chromium browser.
- Store local job data under `output/shared/`.
- Start the API on `http://localhost:8000`.

For local development, use:

```bash
export CRAWLER_URL=http://localhost:8000
```

## 2. Test the API

Open your browser and visit:

- API Documentation: `$CRAWLER_URL/docs`
- Alternative Docs: `$CRAWLER_URL/redoc`

For Docker defaults, those resolve to:

- http://localhost:8041/docs
- http://localhost:8041/redoc

## 3. Submit Your First Crawl Job

Every crawl job must include a `job_id`. Use a unique value so repeated runs do
not reuse the same job directory.

### Using cURL

```bash
JOB_ID="quickstart-$(date +%Y%m%d-%H%M%S)"

curl -X POST "$CRAWLER_URL/crawl" \
  -H "Content-Type: application/json" \
  -d "{
    \"job_id\": \"$JOB_ID\",
    \"url\": \"https://example.com\",
    \"max_pages\": 5,
    \"discovery_mode\": true
  }"
```

The response includes your `job_id`, an event name, response data, and a
timestamp:

```json
{
  "job_id": "quickstart-20260615-120000",
  "event": "job_submitted",
  "data": {
    "status": "pending",
    "message": "Crawl job submitted successfully"
  },
  "timestamp": "2026-06-15T10:00:00.000000Z"
}
```

### Using Python

```python
import os
import uuid

import requests

base_url = os.getenv("CRAWLER_URL", "http://localhost:8041")
job_id = f"quickstart-{uuid.uuid4()}"

response = requests.post(f"{base_url}/crawl", json={
    "job_id": job_id,
    "url": "https://example.com",
    "max_pages": 5,
    "discovery_mode": True,
})
response.raise_for_status()

print(f"Job ID: {response.json()['job_id']}")
```

## 4. Check Job Status

```bash
curl "$CRAWLER_URL/status/$JOB_ID"
```

Or use the example client from the repo root:

```bash
python examples/example_client.py list
```

The example client uses `CRAWLER_URL` or `CRAWLER_API_BASE_URL` when set. If
neither is set, it defaults to the Docker API URL: `http://localhost:8041`.

## 5. Find Your Results

Docker stores job data in the external `rawki_shared_storage` volume at:

```text
/var/www/html/shared/{job_id}/
```

Local development via `start_server.sh` stores job data under:

```text
output/shared/{job_id}/
```

Current page output uses hash-based page directories:

```text
{job_id}/
|-- job_state.json
|-- summary.json
`-- pages/
    `-- a/b/c/d/{url_hash}/
        |-- data.json
        |-- content.md
        |-- images/
        `-- files/
```

You can also list job files through the API:

```bash
curl "$CRAWLER_URL/jobs/$JOB_ID/files"
```

## Common Use Cases

Change the example `job_id` values before rerunning the same request.

### Crawl a Sitemap

```bash
curl -X POST "$CRAWLER_URL/crawl" \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "sitemap-example",
    "url": "https://example.com/sitemap.xml",
    "max_pages": 100
  }'
```

### Crawl with URL Discovery

```bash
curl -X POST "$CRAWLER_URL/crawl" \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "discovery-example",
    "url": "https://example.com",
    "max_pages": 50,
    "discovery_mode": true,
    "max_concurrency": 5
  }'
```

### Skip Images

```bash
curl -X POST "$CRAWLER_URL/crawl" \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "skip-images-example",
    "url": "https://example.com",
    "max_pages": 100,
    "skip_images": true,
    "max_rpm": 120
  }'
```

### Extract Dates

```bash
curl -X POST "$CRAWLER_URL/crawl" \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "date-example",
    "url": "https://example.com",
    "max_pages": 50,
    "date_selector": "time, .date, meta[property=\"og:updated_time\"]"
  }'
```

## Configuration Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `job_id` | required | Unique identifier for the crawl job and output directory. |
| `url` | required | Starting URL. |
| `max_pages` | 100 | Max pages to crawl. Use `0` for unlimited. |
| `discovery_mode` | false | Auto-discover URLs from crawled pages. |
| `skip_images` | false | Skip downloading images. |
| `max_concurrency` | 4 | Parallel requests. |
| `max_rpm` | 60 | Requests per minute. |
| `date_selector` | null | CSS selector for date extraction. |
| `max_link_density` | 0.4 | Allows content where up to about 40% is link text. Raise to `0.6`/`0.8` if useful pages are missing; lower to `0.2`/`0.3` if too many navigation/list pages are included. |

See [README.md](README.md) and [_documentation/README.md](_documentation/README.md)
for more documentation.

## Troubleshooting

### Docker Issues

#### External volume or network missing

If `docker compose up` reports that `rawki_shared_storage` or `hawki-network`
does not exist, create them:

```bash
docker volume create rawki_shared_storage
docker network create hawki-network
```

If the network already exists, Docker may print an error for the second command.
That is fine.

#### Container will not start

```bash
docker compose logs crawler
docker compose down
docker compose build --no-cache
docker compose up -d
```

#### Port Already in Use

Docker publishes host port `8041` to container port `80`. If host port `8041` is
already in use, edit `docker-compose.yml`:

```yaml
ports:
  - "8080:80"
```

Then use:

```bash
export CRAWLER_URL=http://localhost:8080
```

For local development, set a different port when starting the script:

```bash
PORT=8080 ./start_server.sh
export CRAWLER_URL=http://localhost:8080
```

### Local Development Issues

#### Playwright Issues

Manually install Playwright browsers:

```bash
uv run playwright install chromium
```

If you used the fallback virtual environment path:

```bash
source env/bin/activate
python -m playwright install chromium
```

#### Permission Errors

Ensure the local output directory is writable:

```bash
mkdir -p output/shared
chmod 755 output output/shared
```

#### Memory Issues

If you encounter memory issues with Docker, increase Docker memory or adjust the
limits in `docker-compose.yml`:

```yaml
deploy:
  resources:
    limits:
      memory: 8G
```

## Next Steps

- Read [README.md](README.md) and [_documentation/README.md](_documentation/README.md).
- Try the example client: `python examples/example_client.py`.
- Check the interactive API docs: `$CRAWLER_URL/docs`.
- Customize your crawl with image exclusions, rate limiting, and URL discovery.

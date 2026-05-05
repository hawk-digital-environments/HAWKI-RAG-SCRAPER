# Quick Start Guide

Get the Crawl4AI FastAPI service running in 5 minutes!

## Choose Your Setup Method

### Option 1: Docker (Recommended) ⭐

**Fastest way to get started!**

```bash
# Start the service with Docker
docker compose up -d

# The service is now running at http://localhost:8000
```

That's it! Docker will automatically:
- Build the container with all dependencies
- Install Playwright browsers
- Start the server
- Mount the output directory for your crawled data

### Option 2: Local Development

```bash
# Make the start script executable (if not already)
chmod +x start_server.sh

# Start the server (this will automatically set up everything)
./start_server.sh
```

The script will:
- Create a virtual environment
- Install all dependencies
- Install Playwright browsers
- Start the server on http://localhost:8000

## 2. Test the API

Open your browser and visit:
- **API Documentation**: http://localhost:8000/docs
- **Alternative Docs**: http://localhost:8000/redoc

## 3. Submit Your First Crawl Job

### Using cURL

```bash
curl -X POST "http://localhost:8000/crawl" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "max_pages": 5,
    "discovery_mode": true
  }'
```

You'll get a response with a `job_id`:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Crawl job submitted successfully",
  "status": "pending"
}
```

### Using Python

```python
import requests

response = requests.post("http://localhost:8000/crawl", json={
    "url": "https://example.com",
    "max_pages": 5,
    "discovery_mode": True
})

job_id = response.json()["job_id"]
print(f"Job ID: {job_id}")
```

## 4. Check Job Status

```bash
# Replace {job_id} with your actual job ID
curl "http://localhost:8000/status/{job_id}"
```

Or use the example client:
```bash
python example_client.py list
```

## 5. Find Your Results

Results are saved in the `output/` directory:

```
output/
└── example_com_20250321_143022/
    ├── images/
    ├── data_00001.json
    ├── site_00001.md
    └── ...
```

## Common Use Cases

### Crawl a Sitemap
```bash
curl -X POST "http://localhost:8000/crawl" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/sitemap.xml",
    "max_pages": 100
  }'
```

### Crawl with URL Discovery
```bash
curl -X POST "http://localhost:8000/crawl" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "max_pages": 50,
    "discovery_mode": true,
    "max_concurrency": 5
  }'
```

### Skip Images (Faster Crawling)
```bash
curl -X POST "http://localhost:8000/crawl" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "max_pages": 100,
    "skip_images": true,
    "max_rpm": 120
  }'
```

### Extract Dates
```bash
curl -X POST "http://localhost:8000/crawl" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "max_pages": 50,
    "date_selector": "time, .date, meta[property=\"og:updated_time\"]"
  }'
```

## Configuration Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `url` | *required* | Starting URL |
| `max_pages` | 100 | Max pages to crawl |
| `discovery_mode` | false | Auto-discover URLs |
| `skip_images` | false | Skip downloading images |
| `max_concurrency` | 4 | Parallel requests |
| `max_rpm` | 60 | Requests per minute |
| `max_link_density` | 0.4 | Allows content where up to ~40% is link text. Raise to `0.6`/`0.8` if useful pages are missing; lower to `0.2`/`0.3` if too many navigation/list pages are included. |

See [README.md](README.md) for complete documentation.

## Troubleshooting

### Docker Issues

#### Container won't start
```bash
# Check container logs
docker compose logs crawler

# Rebuild the container
docker compose down
docker compose build --no-cache
docker compose up -d
```

#### Port Already in Use
If port 8000 is already in use, edit `docker-compose.yml`:
```yaml
ports:
  - "8080:8000"  # Change 8000 to 8080 or any available port
```

Or for local development, edit `start_server.sh`:
```bash
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

### Local Development Issues

#### Playwright Issues
Manually install Playwright browsers:
```bash
source env/bin/activate
playwright install chromium
```

#### Permission Errors
Ensure the output directory is writable:
```bash
mkdir -p output
chmod 755 output
```

#### Memory Issues
If you encounter memory issues with Docker:

1. Increase Docker memory limit (Docker Desktop → Settings → Resources)
2. Or adjust limits in `docker-compose.yml`:
```yaml
deploy:
  resources:
    limits:
      memory: 4G  # Increase as needed
```

## Next Steps

- Read the full [README.md](README.md) for advanced features
- Try the example client: `python example_client.py`
- Check the interactive API docs: http://localhost:8000/docs
- Customize your crawl with image exclusions and rate limiting

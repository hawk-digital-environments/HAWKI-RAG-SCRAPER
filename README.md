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


### Using Docker

```bash
# Build and start the service
docker compose up -d

# View logs
docker compose logs -f

# Stop the service
docker compose down
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

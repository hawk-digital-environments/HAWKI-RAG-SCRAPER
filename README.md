# Crawl4AI FastAPI Service

A FastAPI interface for the crawl4ai library with sitemap support, URL discovery,
rate limiting, structured page output, and a SvelteKit admin UI.

## Features

- Sitemap parsing and profile-driven sitemap scraping.
- URL discovery from crawled pages.
- Configurable request rate and concurrency.
- Image, PDF, and supported file downloading.
- JSON metadata and Markdown content output.
- Persistent per-job state, URL tracking, logs, and summaries.

## Quick Start

See [QUICKSTART.md](QUICKSTART.md) for a full setup walkthrough.

For Docker, create the external storage volume and network once, then start the
service:

```bash
docker volume create rawki_shared_storage
docker network create hawki-network 2>/dev/null || true
docker run --rm -v rawki_shared_storage:/data alpine chown -R "${PUID:-1000}:${PGID:-1000}" /data
docker compose up -d
```

The Docker API is available at:

```bash
http://localhost:8041
```

Useful commands:

```bash
docker compose logs -f crawler
docker compose down
```

## Local Development

```bash
chmod +x start_server.sh
./start_server.sh
```

The local API defaults to `http://localhost:8000` and stores job output under
`output/shared/`.

## Output

Docker stores crawl jobs in the `rawki_shared_storage` volume at
`/var/www/html/shared/{job_id}/`. Each job includes persistent state and
hash-based page output:

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

## Documentation

Comprehensive documentation is available in the [_documentation](_documentation)
folder:

- [API Reference](_documentation/API_REFERENCE.md)
- [External Runtime Contract and Browser Safety Gate](_documentation/EXTERNAL_RUNTIME.md)
- [Architecture](_documentation/ARCHITECTURE.md)
- [Deployment Guide](_documentation/DEPLOYMENT.md)
- [Configuration Guide](_documentation/CONFIGURATION.md)
- [Developer Guide](_documentation/DEVELOPER_GUIDE.md)

## License

MIT

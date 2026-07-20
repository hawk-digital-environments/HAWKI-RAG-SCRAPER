# Crawler Package

The `hawki_crawler` package contains the FastAPI application, crawler runtime,
state tracking, parsing, asset downloading, sitemap helpers, and storage layer.

## Package Layout

```text
hawki_crawler/
|-- app/              FastAPI routes and crawl job lifecycle
|-- common/           Logging setup and shared internal helpers
|-- crawler/
|   |-- assets/       Image, PDF, and file download helpers
|   |-- core/         Runtime initialization and crawl execution
|   |-- parsing/      HTML, Markdown, date, language, and quality parsing
|   |-- policies/     URL normalization and filtering
|   |-- profiles/     Site profile loading
|   |-- sitemap/      Sitemap parsing and scraping
|   |-- state/        Job state, progress tracker, lifecycle stages
|   `-- storage/      Job directories, page output, manifests, summaries
`-- scripts/          Dataset validation and maintenance scripts
```

## State

`JobState` persists crawl progress to `job_state.json` in the job directory.
`ProgressTracker` keeps in-memory counters for summaries and API status updates.

## Storage

`StorageManager` owns the per-job directory under `/var/www/html/shared` in
Docker or `output/shared` for local development. Page data is stored under
hash-based directories:

```text
{job_id}/pages/{hash[0]}/{hash[1]}/{hash[2]}/{hash[3]}/{full_hash}/
|-- data.json
|-- content.md
|-- images/
`-- files/
```

## Scripts

- `hawki_crawler/scripts/validate_dataset.py`
- `hawki_crawler/scripts/rebuild_completed_manifest.py`
- `hawki_crawler/scripts/debug_crawler.py`

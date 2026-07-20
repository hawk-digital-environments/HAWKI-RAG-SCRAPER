# Crawler Job UI

SvelteKit dashboard for:

- submitting crawl jobs with backend crawl parameters
- monitoring running jobs with URL counts
- managing reusable profile JSON templates
- inspecting job details, summaries, and logs

## Run

```sh
cd ui
npm install
CRAWLER_API_BASE_URL=http://127.0.0.1:8041 npm run dev -- --open
```

From the repository root, `make start-ui` sets the same crawler API default. The Docker-served UI is available at `http://localhost:8041/ui/`; use the Vite URL only while the dev server is running.

## Env Variables

The UI server proxies requests to the crawler API.

```sh
CRAWLER_API_BASE_URL=http://127.0.0.1:8041
```

## API Routes in UI

- `POST /api/crawler/submit` -> `POST {CRAWLER_API_BASE_URL}/crawl`
- `GET /api/crawler/jobs` -> `GET {CRAWLER_API_BASE_URL}/jobs`
- `GET /api/crawler/job/[jobId]/summary` -> reads crawler file APIs and derives URL counts

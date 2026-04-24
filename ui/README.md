# Crawler Job UI (SvelteKit)

SvelteKit dashboard for:
- submitting crawl jobs with Makefile-style and backend crawl parameters
- viewing RabbitMQ queue state
- monitoring jobs with URL counts (`found`, `completed`, `missed`)
- managing reusable university profile JSON templates (browser local storage)

## Run

```sh
cd ui
npm install
npm run dev -- --open
```

## Env Variables

The UI server proxies requests to crawler and RabbitMQ APIs.

```sh
CRAWLER_API_BASE_URL=http://localhost:8040
RABBITMQ_MGMT_API_URL=http://localhost:15672/api
RABBITMQ_MGMT_USER=guest
RABBITMQ_MGMT_PASSWORD=guest
```

## API Routes in UI

- `POST /api/crawler/submit` -> `POST {CRAWLER_API_BASE_URL}/crawl`
- `GET /api/crawler/jobs` -> `GET {CRAWLER_API_BASE_URL}/jobs`
- `GET /api/crawler/job/[jobId]/summary` -> reads crawler file APIs and derives URL counts
- `GET /api/rabbitmq/queues` -> `GET {RABBITMQ_MGMT_API_URL}/queues`

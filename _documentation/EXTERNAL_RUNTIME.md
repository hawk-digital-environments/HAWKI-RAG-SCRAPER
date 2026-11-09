# External crawler runtime contract

CustomCrawler executes external jobs. HAWKI-RAG remains responsible for auth,
datasets, URL generations, Temporal, recrawl schedules, indexer orchestration,
Qdrant/Neo4j cleanup and artifact retirement. No callbacks or generation
authority are added here.

## Current activation status

**Browser crawling requires the protected Linux namespace transport.** Full
HTML crawls, quick `/scrape` and rendered/paginated sitemaps launch Chromium only
inside fresh user/network/PID namespaces. Without the required namespace
permission, startup fails closed. HTTP fetching remains independently available.

Chromium has only namespace-local loopback connectivity and no external route.
A private Unix-socket bridge reaches the parent-side validating broker. HTTP
uses SafeSession; CONNECT and WebSocket sockets resolve and connect to approved
numeric addresses. HTTPS remains end-to-end, without TLS interception. Direct
connections cannot reach external targets even if proxy bypass is requested.
There is no environment switch that disables the boundary. See
[browser egress deployment and validation](../docker/BROWSER_EGRESS.md).

The consuming RAWKI checkout also has independent, unconditional URL/sitemap
safe-fetch gates in its backend and scraper worker. Those remain unchanged.
Passing the runtime receipt contract does not activate that ingestion path.

## API

- `POST /crawl`: requires a permanent `job_id` and an HTTP(S) `url`. A new job
  returns the existing `job_submitted` envelope. Identical retries return
  `job_exists` and the existing status, including after sealing. Different
  payloads with the same ID return 409. Neither case launches duplicate work.
- `GET /status/{job_id}`: returns durable state, including after restart or
  artifact retirement. Missing IDs return 404; invalid IDs return 422.
- `GET /jobs`: lists durable jobs other than acknowledged retirements.
- `POST /jobs/{job_id}/cancel`: persists cancellation intent and closes network
  admission before cancellation. Waits up to one second for drainage; may return
  `cancelling` with `sealed=false`. Poll status until a sealed receipt arrives.
  Repeating cancellation does not interrupt cancellation cleanup a second time.
- Pause/resume are cooperative controls of live, admitted jobs only. Cancelled,
  sealed and recovered-unknown jobs cannot resume.
- `DELETE /jobs/{job_id}`: returns 409 for active/unconfirmed jobs. For sealed
  jobs, retires the listing entry while retaining the permanent receipt and
  artifacts. HAWKI-RAG decides when to remove artifacts. This endpoint does not
  clean Qdrant/Neo4j or erase the write fence.

A status receipt includes:

```json
{
  "job_id": "caller-stable-id",
  "external_job_id": "caller-stable-id",
  "status": "cancelled",
  "state": "cancelled",
  "created_at": "...",
  "started_at": "...",
  "finished_at": "...",
  "cancel_requested": true,
  "terminal": true,
  "sealed": true,
  "sealed_at": "...",
  "quiescent": true,
  "writer_admission_closed": true,
  "output_directory": "/var/www/html/shared/.../caller-stable-id"
}
```

The extra `quiescent` and `writer_admission_closed` fields are required by
HAWKI-RAG's actual retirement client. Terminal status alone is insufficient.
`source_id`, `source_url`, `generation`, `url_ingestion_operation_id` and
`metadata`, when supplied, are retained as opaque metadata. The current
HAWKI-RAG start-payload builder does not forward every generation field.

## Durability, drainage and writer fence

`DATA_PATH/.crawler-runtime` stores atomically replaced, fsynced receipts,
request fingerprints and permanent writer fences. Preserve this directory
when retiring artifacts or restoring backups. Erasing it erases idempotency
evidence. Use a local filesystem with reliable POSIX file locks and fsync.

One runtime process owns a DATA_PATH via an exclusive lock, including throughout
shutdown drainage. Multiple API workers/replicas sharing that path fail startup
rather than splitting execution ownership. The existing image uses one worker.
`MAX_CONCURRENT_TASKS` bounds admitted unsealed jobs (default 5); a full runtime
returns 429 without creating a job. Unknown recovered work conservatively keeps
its reservation. Identical retries do not consume additional reservations.

Job scopes track asyncio children, delayed timers, safe HTTP sessions and file
handles. Cancellation closes network admission, awaits the executor, cancels
and drains descendants, closes HTTP sessions and writers, and removes delayed
work before persisting a terminal sealed receipt. Work that does not drain
stays unsealed; polling/cancellation never substitutes a timeout for proof.

All runtime artifact/progress writers use one admission helper. File writes
are synchronous local operations under shared per-job writer leases, avoiding
abandoned executor-thread writes. Seal requires an exclusive lease and refuses
confirmation while any writer holds a lease. Late writes/restarts are rejected.
The job log handler opens a fenced stream per emission and retains no writer.
The guarantee covers this runtime's managed writers, not unrelated processes
with arbitrary write access to the shared volume.

Previously unsealed work becomes `unknown`, `terminal=false`, `sealed=false`
on startup. Legacy job-state directories also become unconfirmed records.
Neither process death nor an old terminal file proves drainage. Unknown work
requires independent operational reconciliation; there is no automatic force
seal or reset endpoint. New IDs cannot reuse/overlap an old artifact root.

Default artifact roots remain `DATA_PATH/<job_id>`. A supplied shared
`output_dir` instead receives its own `<job_id>` child directory; known
`/shared`, `/app/shared`, `/var/www/html/shared` prefixes map to DATA_PATH.
This keeps HAWKI-RAG's source/raw retirement tree and permanent job roots
compatible. Traversal, arbitrary external paths and overlapping roots are
rejected. Persistent sitemap output must remain within that job root too.

## HTTP network enforcement

Every runtime aiohttp surface uses SafeSession: HEAD, images, PDFs/files,
fallback HTML, initial/nested sitemap resources. Only HTTP(S) is accepted.
DNS results must all be public. The socket factory rechecks the numeric
destination actually handed to the connector, including IP literals, so the
transport never reconnects by resolving the original hostname again. DNS cache
and connection reuse are disabled. Redirects are bounded and processed through
the same transport hop by hop. Host/SNI remain the original hostname and TLS
certificate validation remains enabled. Proxy/TLS bypass arguments and ambient
proxy configuration are disallowed.

Loopback, private, link-local, unspecified, multicast, reserved, metadata and
IPv6 transition destinations are rejected. Each safe session owns its DNS
executor and drains/joins outstanding resolution before reporting closed. An
OS resolver timeout may delay drainage; cancellation cannot leave an abandoned
DNS thread behind a sealed receipt. No production loopback exception exists.

## Trust boundary and validation

The API intentionally remains private; it does not authenticate bearer tokens
that the consumer optionally sends. HAWKI-RAG has no shared signed scraper-call
protocol to reuse here. Production Compose still defaults to loopback. An
external access-controlled proxy or equivalent network isolation is required.
The development Compose bind is broader and is not that production boundary.

Run Python tests with `python -m pytest`, UI regression tests with
`node --test ui/tests/crawler-client.test.js`, and existing UI checks/build with
`npm --prefix ui run check` / `npm --prefix ui run build`. Optional consumer
contract tests import the local RAWKI checkout without writing bytecode there;
they skip if it or its test dependencies are absent. Positive local TCP tests
use an explicit test-only policy substitution, never a production setting.
They do not demonstrate a successful browser or Temporal/indexer crawl.

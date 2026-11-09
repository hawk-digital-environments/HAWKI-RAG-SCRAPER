# Secure Browser Egress for CustomCrawler

This branch adds a hardened browser-execution boundary to **CustomCrawler** so it can be safely used as the external crawler runtime for **HAWKI-RAG URL ingestion**.

The main goal is simple:

> HAWKI-RAG should be able to ask CustomCrawler to render and crawl arbitrary public URLs without allowing Chromium to reach localhost, private networks, cloud metadata endpoints, or any other destination that was not explicitly validated.

This work also strengthens the external job lifecycle so HAWKI-RAG can safely decide when a crawl is finished, cancelled, quiescent, and safe to retire.

---

## Why this was needed

Before this branch, CustomCrawler already supported browser crawling, sitemaps, assets, status polling, and filesystem artifacts, but several guarantees required by HAWKI-RAG were missing.

The most important gaps were:

- browser traffic was not connection-bound to an approved destination;
- redirects and browser subresources could potentially reach destinations that were never validated;
- DNS validation alone could not protect against DNS rebinding;
- cancellation did not prove that all writers and network activity had stopped;
- duplicate job submissions could overlap;
- sealed/retired job state was not durable enough for HAWKI-RAG deletion and recrawl decisions.

Because URL ingestion accepts user-controlled URLs, these are security and correctness requirements rather than optional hardening.

---

## Architecture

The browser no longer receives normal host networking.

Instead, Chromium runs inside isolated Linux namespaces and all of its network traffic is forced through a validating egress path:

```text
HAWKI-RAG
    |
    | start / status / cancel
    v
CustomCrawler API
    |
    v
Chromium
    |
    | isolated Linux network namespace
    v
Namespace-local proxy bridge
    |
    | private Unix socket
    v
Validating egress broker
    |
    | resolve + validate + connect to approved numeric IP
    v
Public destination
```

The browser cannot directly reach the external network.

If the secure browser boundary cannot be created, browser crawling **fails closed**. CustomCrawler never falls back to launching Chromium with unrestricted networking.

---

## What the egress broker protects against

### SSRF

A crawler that accepts arbitrary URLs can otherwise be abused to request internal services on behalf of a user.

Examples of destinations that must not be reachable include:

```text
127.0.0.1
::1
10.0.0.0/8
172.16.0.0/12
192.168.0.0/16
169.254.0.0/16
169.254.169.254
IPv6 private/link-local equivalents
```

The important guarantee is not just that the URL was checked before the request.

The **actual network connection** is made to the numeric IP address that passed the security policy.

---

### DNS rebinding

A malicious hostname can resolve to a public IP during validation and then change to a private IP before the real connection happens.

To prevent this, the validated destination and the actual connection are tied together. The broker does not validate one DNS answer and then allow the client to independently resolve the hostname again.

---

### Redirects

Every new redirect destination is validated before a connection is opened.

For example:

```text
https://public.example
        |
        | 302
        v
http://169.254.169.254
```

The second request is rejected before Chromium can connect to it.

---

### Browser subresources

Protecting only the top-level page is not sufficient.

A public page can reference private resources through:

- JavaScript
- CSS
- images
- iframes
- `fetch()` / XHR
- WebSockets
- redirects
- background browser traffic

All supported browser traffic goes through the same validated egress boundary.

QUIC / HTTP3 is disabled so Chromium cannot bypass the controlled TCP proxy path using direct UDP traffic.

---

## HTTPS and TLS

HTTPS is not intercepted or downgraded.

For HTTPS destinations the broker validates the destination, connects to the approved numeric address, and preserves the original hostname for the browser's normal TLS session.

This means:

- SNI remains correct;
- normal certificate validation remains enabled;
- wrong-host certificates are still rejected;
- there is no custom TLS MITM certificate authority.

---

## Linux namespace isolation

Chromium runs inside fresh Linux namespaces with capabilities dropped.

The network namespace is especially important: even if Chromium or Playwright is configured to bypass the proxy, the browser process still has no direct route to external or private networks.

This gives us two independent protections:

```text
Application layer
    -> validating proxy / broker

Kernel isolation
    -> Chromium has no direct external route
```

The browser is therefore not relying only on Playwright request interception or URL filtering.

---

## Seccomp profile

The feature includes:

```text
docker/browser-seccomp.json
```

Docker normally applies a seccomp policy that restricts sensitive Linux system calls. The secure browser runtime needs a small set of namespace-related operations in order to create the isolated browser environment.

The supplied seccomp profile enables the required namespace setup while keeping the container restricted.

The deployment must explicitly use the documented profile. If the required namespace/security setup is unavailable, browser execution fails closed.

See:

```text
docker/BROWSER_EGRESS.md
```

for the deployment requirements.

---

## HAWKI-RAG runtime contract

CustomCrawler remains an **execution runtime**, not the owner of RAG business logic.

HAWKI-RAG continues to own:

- authentication and authorization;
- datasets;
- URL/source identity;
- ingestion generations;
- Temporal workflows;
- recrawl scheduling;
- Qdrant indexing and cleanup;
- Neo4j graph indexing and cleanup;
- final deletion and retirement decisions.

CustomCrawler owns only the external crawl execution and its local artifact lifecycle.

The relevant contract is:

```text
POST /crawl
GET  /status/{job_id}
POST /jobs/{job_id}/cancel
```

A job exposes durable lifecycle evidence including:

```text
job_id
status
terminal
sealed
sealed_at
quiescent
writer_admission_closed
```

HAWKI-RAG must not retire a crawl generation merely because the crawl is terminal.

Retirement is safe only after the external runtime confirms:

```text
terminal = true
quiescent = true
writer_admission_closed = true
sealed = true
```

and HAWKI-RAG's own managed writers are also drained.

---

## Job idempotency

`job_id` is a permanent execution identity.

Submitting the same request again does not start duplicate crawl work.

Expected behavior:

```text
new job_id + new payload
    -> accepted

same job_id + identical payload
    -> existing job returned

same job_id + conflicting payload
    -> rejected

sealed job_id + restart attempt
    -> rejected
```

This protects HAWKI-RAG from duplicate crawler execution after an ambiguous HTTP retry or lost response.

---

## Cancellation and quiescence

Cancellation is no longer treated as equivalent to cleanup being safe.

The runtime drains:

- crawl execution;
- browser processes;
- proxy connections;
- DNS work;
- HTTP sessions;
- timers/background tasks;
- Playwright control processes;
- managed artifact writers.

Only after these resources are drained can the job become sealed.

Conceptually:

```text
running
   |
   v
cancelling
   |
   v
terminal
   |
   | all runtime resources drained
   v
quiescent
   |
   | writer admission permanently closed
   v
sealed
```

Once sealed, the job cannot resume and managed writers may not modify its artifact tree.

---

## Writer fencing

A central writer-admission boundary protects crawler-managed artifacts.

After a job is sealed, late writes are rejected for areas such as:

- page content;
- metadata;
- downloaded assets;
- manifests;
- sitemap data;
- progress state;
- managed logs.

Writer leases also prevent the runtime from marking a job sealed while a managed writer is still active.

---

## Sitemap safety

HTTP sitemap handling uses the same safe connection-bound transport.

This applies to:

- the initial sitemap;
- sitemap redirects;
- nested sitemap indexes;
- URLs discovered from sitemap content.

A sitemap cannot be used as a separate SSRF path.

---

## Global admission limit

`MAX_CONCURRENT_TASKS` now limits the number of admitted, unsealed crawl jobs.

When capacity is exhausted, new work is rejected instead of silently creating additional crawler jobs.

Capacity is released correctly after terminal/sealed cleanup and error paths.

---

## SvelteKit mutation retry behavior

Read requests may still use upstream failover where appropriate.

Mutation requests such as `POST /crawl` are treated differently because automatically retrying a POST against another runtime after an ambiguous network failure could create duplicate execution.

Server-side `job_id` idempotency provides an additional safety layer.

---

## Fail-closed behavior

The security boundary is mandatory.

If any required browser isolation component is unavailable, for example:

- namespace creation fails;
- the broker cannot start;
- the secure transport cannot initialize;
- required deployment permissions are missing;

then protected browser crawling is not started.

There is intentionally no fallback to ordinary unrestricted Chromium networking.

---

## Validation

The implementation has been validated with focused lifecycle, transport, browser, and integration tests.

At the time this branch was prepared:

```text
Linux Python suite:               137 passed, 2 skipped
Host Python suite:                110 passed, 29 skipped
Production-image browser suite:    29 passed
JavaScript tests:                   2 passed
Svelte checks:                      0 errors, 0 warnings
Docker test build:                 passed
Docker production build:           passed
Ruff / formatting:                 passed
git diff --check:                  passed
```

The browser integration tests cover, among other things:

- normal rendered Chromium crawling;
- private and loopback destination rejection;
- cloud metadata rejection;
- safe and unsafe redirects;
- DNS rebinding attempts;
- CSS/JS/image/iframe subresources;
- `fetch()` / XHR;
- WebSockets;
- HTTPS hostname/SNI verification;
- explicit proxy bypass attempts;
- browser cancellation and quiescence;
- sealing and late-write rejection.

---

## Deployment requirement

This branch changes application behavior, but it does **not** automatically change production deployment configuration.

Before enabling browser URL ingestion in HAWKI-RAG, the deployed CustomCrawler container must satisfy the namespace/seccomp requirements documented in:

```text
docker/BROWSER_EGRESS.md
```

and use:

```text
docker/browser-seccomp.json
```

Do not enable Python browser ingestion until the deployed crawler passes its runtime/readiness validation.

---

## Responsibility boundary

The intended final architecture is:

```text
HAWKI-RAG
  |
  | authentication / authorization
  | generation + Temporal orchestration
  v
CustomCrawler
  |
  | safe browser execution
  | durable job lifecycle
  | cancel / drain / seal
  v
Shared artifacts
  |
  v
HAWKI-RAG indexer
  |             |
  v             v
Qdrant        Neo4j
```

CustomCrawler deliberately does **not** contain HAWKI-RAG generation authority, scheduling, Qdrant/Neo4j cleanup, mixed-owner recovery, or dataset authorization.

Keeping this boundary narrow makes the crawler reusable while keeping RAG lifecycle decisions in the service that owns them.

---

## Summary

This branch turns CustomCrawler from a general browser crawler into a runtime that HAWKI-RAG can safely treat as an external ingestion dependency.

The key properties are:

- Chromium cannot directly reach arbitrary network destinations;
- browser and HTTP traffic are connection-bound to validated destinations;
- redirects, sitemaps, WebSockets, and subresources follow the same security boundary;
- DNS rebinding is prevented;
- duplicate crawler jobs are prevented;
- cancellation is distinguishable from true quiescence;
- sealed jobs cannot write again;
- lifecycle evidence survives long enough for HAWKI-RAG to make safe deletion and recrawl decisions;
- unsafe or misconfigured deployments fail closed rather than falling back to unrestricted crawling.

With the deployment prerequisites in place, this provides the external crawler contract required for HAWKI-RAG Epoch 11 URL ingestion.

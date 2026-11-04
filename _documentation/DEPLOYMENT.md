# Deployment

The scraper ships as a single prebuilt Docker image:
[digitalenvironments/hawki-rag-scraper](https://hub.docker.com/r/digitalenvironments/hawki-rag-scraper).
The image is self-contained: nginx, gunicorn with the FastAPI crawl API, the
SvelteKit frontend server and the Playwright chromium browser all run inside
it. A production server pulls the image and runs it; nothing is built from
source. The host needs Docker with Compose v2 and the preconfigured setup from
the repository.

## Docker Compose

The [`_docker_production`](../_docker_production) directory holds the
preconfigured production setup: a pull-only `docker-compose.yml` that runs the
scraper as one standalone service. The stack joins no shared network; anything
that needs the scraper goes through its published port.

**Please consider it a starting point you can/should adapt to your needs.**

Image versions are pinned in `.env`: `HAWKI_RAG_SCRAPER_VERSION` selects the
release, `HAWKI_RAG_SCRAPER_IMAGE_REPOSITORY` the registry. The public image is
published as `latest`, `<major>` and `<version>` tags. Our own servers do not
use the public releases: the `deploy-scraper-*` workflows build internal images
and push them to the GitHub Container Registry as `prod-latest` and
`test-1-latest`, so an internal deployment sets
`HAWKI_RAG_SCRAPER_IMAGE_REPOSITORY=ghcr.io/hawk-digital-environments/customcrawler`
and pins `HAWKI_RAG_SCRAPER_VERSION` accordingly.

A few things to consider:

* Certificates - Place your own certificates as `cert.pem` and `key.pem` in the
  `certs` directory. They are mounted into the container, which then terminates
  HTTPS itself. Without certificates the container generates self-signed ones
  (expect browser warnings).
* Reverse proxy - The container binds
  `${DOCKER_PROJECT_IP:-127.0.0.1}:${HAWKI_RAG_SCRAPER_PORT:-8041}:80`, loopback
  by default, so an external reverse proxy terminates TLS and forwards traffic
  to it. Set `ORIGIN` to the public URL; see
  [Reverse proxy and HTTPS](#reverse-proxy-and-https).
* Persistent data - Profiles, task definitions and output live in named
  volumes owned by this stack. Crawl results go into `rawki_shared_storage`, a
  volume with the same fixed name the HAWKI RAG production stack uses, so that
  stack can read the crawled data from the same volume even though the two
  stacks share no network. Whichever stack starts first creates the volume.
* Forbidden URLs - `forbidden_urls.txt` is bind-mounted into the container.
  Edit the copy in `_docker_production`; lines are either forbidden hostnames
  or URL patterns, and `#` comments are allowed.
* Configuration - Copy `.env.example` to `.env` and adjust it. The file is
  the configuration reference for this stack: extend it rather than guessing
  variable names.

:::warning The API has no authentication

The API is deliberately left unauthenticated for now: everyone who can reach
the published port can start crawl jobs and manage running ones. Keep the
loopback binding, put a reverse proxy with its own access control in front,
or restrict access on the network level.

:::

The container runs everything as `www-data` (uid/gid 33). `PUID`/`PGID` in
`.env` remap that user; match them to the owner of `rawki_shared_storage` when
the volume already carries data from another stack.

### What's in the box

The compose file defines one service:

* `crawler` - The complete scraper. Inside the image, supervisor manages three
  processes: nginx (port 80, health-checked via `/health`), gunicorn serving
  the FastAPI crawl API, and the SvelteKit frontend server (the admin UI at
  `/ui/`). Playwright's chromium ships inside the image, so crawl jobs render
  pages without any host browser. See [Architecture](./ARCHITECTURE.md) for the
  internal request flow.

Data lives in four volumes (`profiles_storage`, `tasks_storage`,
`output_storage`, and the shared `rawki_shared_storage`) plus two bind mounts
(`forbidden_urls.txt` and `certs`). The container reports healthy once
`/health` answers, usually about half a minute after start.

### Deployment

Put the `_docker_production` directory on the server (cloning the repository
works), then:

```bash
cd _docker_production
cp .env.example .env
chmod +x deploy.sh && ./deploy.sh
```

`deploy.sh` runs `docker compose up --pull always -d`: it pulls the pinned
image and starts the service. Wait for the health check to pass, then verify:

```bash
docker compose ps                      # wait until STATUS shows (healthy)
curl -s http://127.0.0.1:8041/health  # {"status": "healthy", ...}
```

The admin UI listens at `http://localhost:8041/ui/`. A minimal crawl request
against the API:

```bash
curl -X POST http://127.0.0.1:8041/crawl \
  -H 'content-type: application/json' \
  -d '{"job_id": "smoke-test", "url": "https://example.com", "max_pages": 1}'
```

### Reverse proxy and HTTPS

The container's internal nginx always routes between the Python API and the
SvelteKit frontend, no matter what sits in front. Two ways to expose it:

* Container-terminated HTTPS - Drop `cert.pem` and `key.pem` into `certs/`.
  The container then listens for HTTPS itself.
* External reverse proxy - Keep the default loopback binding and let the proxy
  terminate TLS. It should pass the standard forwarding headers
  (`X-Forwarded-Host`, `X-Forwarded-Proto`, `X-Forwarded-For`) through.

Behind a proxy, set `ORIGIN` to the externally-facing URL: the SvelteKit
server validates the `Origin` header of unsafe requests against it and uses it
to build absolute URLs. For example, if the service is reachable at
`https://scraper.example.com`, set `ORIGIN=https://scraper.example.com`.

The remaining variables are internal wiring with working defaults baked into
the image:

| Variable | Default | Affected by external proxy? |
|---|---|---|
| `ORIGIN` | `http://localhost:80` | **Yes** - must match the public URL |
| `CRAWLER_API_BASE_URL` | `http://localhost:80` | No - internal (SvelteKit → nginx → gunicorn) |
| `NODE_SERVICE_PORT` | `3000` | No - internal (nginx → SvelteKit) |

`PUBLIC_API_BASE_URL` (the public path of the UI, `/ui` by default) is a
different case: the SvelteKit bundle inlines it at image build time via the
`PUBLIC_API_BASE_URL` build argument, so changing it means rebuilding the
image, not editing `.env`.

### Backups

Everything the scraper produces or manages lives in volumes: crawl results in
`rawki_shared_storage`, profiles and task definitions in the stack's own
volumes. Back a volume up by tarring it through a helper container:

```bash
docker run --rm -v rawki_shared_storage:/data -v "$PWD":/backup alpine \
  tar czf /backup/rawki_shared_storage.tar.gz -C /data .
```

Plain `docker compose down` keeps all volumes. `docker compose down -v` also
deletes `rawki_shared_storage` and with it the crawled data shared with the
HAWKI RAG stack - do not use it.

### Building custom images

You can build the image yourself to ship patches or use a private registry.
The root `Dockerfile`'s final stage is the complete production image:

```bash
docker build -t my-registry.example/hawki-rag-scraper:latest .
```

The public releases are built for `linux/amd64` and `linux/arm64`; a custom
build on the target platform works the same way. To serve the UI under a
different public path, pass the build argument instead of editing `.env`:

```bash
docker build --build-arg PUBLIC_API_BASE_URL=/scraper-ui \
  -t my-registry.example/hawki-rag-scraper:latest .
```

Point `HAWKI_RAG_SCRAPER_IMAGE_REPOSITORY` and `HAWKI_RAG_SCRAPER_VERSION` at
your registry and tag, and the production Compose file pulls it like the
official image.

### Troubleshooting

| Symptom | Where to look |
|---|---|
| Container never becomes healthy | `docker compose logs crawler`; the API answers `/health` only after startup finished |
| UI loads, form posts fail with 403 | `ORIGIN` does not match the public URL the browser uses |
| Crawl jobs die with chromium errors | Shared memory or RAM: keep the `/dev/shm` mount, check the memory limit in the compose file |
| `port is already allocated` | Set `HAWKI_RAG_SCRAPER_PORT` to a free port |
| Permission errors writing crawl results | `PUID`/`PGID` do not match the owner of `rawki_shared_storage` |

## Good to know

Upgrading is a re-run: set `HAWKI_RAG_SCRAPER_VERSION` to the new release and
run `./deploy.sh` again. Compose recreates the container from the new image;
all volumes survive, and there is no database migration step. The first start
pulls the image; later starts only pull when the tag changed.

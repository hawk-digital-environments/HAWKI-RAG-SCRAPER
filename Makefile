SITEMAP_PAGES ?= 6
SITEMAP_START ?= 1
SITEMAP_OUTPUT ?= /app/data/sitemap.json
SITEMAP_BASE ?= https://www.hawk.de/sitemaps/main/sitemap.xml
OLLAMA_MODEL ?= qwen2.5:1.5b

# Allow `make cancel <job_id>` as shorthand
ifeq ($(firstword $(MAKECMDGOALS)),cancel)
  ifneq ($(word 2,$(MAKECMDGOALS)),)
    override JOB_ID := $(word 2,$(MAKECMDGOALS))
    $(eval $(word 2,$(MAKECMDGOALS)):=)
  endif
endif

.PHONY: crawl-sitemap crawl-test crawl-full build up down logs

crawl-sitemap:
	docker compose run --rm crawler \
		python services/sitemap_scraper.py --sitemap \
		--base-url $(SITEMAP_BASE) \
		--start-page $(SITEMAP_START) \
		--pages $(SITEMAP_PAGES) \
		--output $(SITEMAP_OUTPUT)



# make profgen DOMAIN=... SITEMAP_URL=https://projekte.g.hawk.de/sitemap [MAX_PAGES=20] [SKIP_FIRST=2] [MODEL=qwen2.5:1.5b]

profgen:
	docker compose run --rm $(if $(SITEMAP_URL),-e SITEMAP_URL=$(SITEMAP_URL),) profile-builder \
		python spb.py $(DOMAIN) \
		--max-pages $(or $(MAX_PAGES),20) \
		$(if $(SITEMAP_URL),--sitemap-url $(SITEMAP_URL),) \
		--output-dir SLM/profiles

crawl-test:
	curl -s -X POST http://localhost:8004/crawl \
		-H "Content-Type: application/json" \
		-d '{"url": "https://www.hawk.de", "hawk_sitemap": true, "sitemap_base": "$(SITEMAP_BASE)", "max_pages": 100, "discovery_mode": true, "skip_images": true, "max_concurrency": 1, "max_rpm": 20}' \
		| python -m json.tool

crawl-full:
	curl -s -X POST http://localhost:8004/crawl \
		-H "Content-Type: application/json" \
		-d '{"url": "https://www.hawk.de", "hawk_sitemap": true, "sitemap_base": "$(SITEMAP_BASE)", "max_pages": 100000, "discovery_mode": true, "skip_images": true, "max_concurrency": 3, "max_rpm": 40}' \
		| python -m json.tool

jobs:
	curl -s http://localhost:8004/jobs | python -m json.tool

cancel:
	@if [ -z "$(JOB_ID)" ]; then echo "Usage: make cancel JOB_ID=<id>  (or make cancel <id>)"; exit 1; fi
	curl -s -X POST http://localhost:8004/jobs/$(JOB_ID)/cancel | python -m json.tool

build:
	docker compose build

up:
	@docker network inspect rawki-network >/dev/null 2>&1 || docker network create rawki-network
	@docker volume inspect rawki_shared_storage >/dev/null 2>&1 || docker volume create rawki_shared_storage >/dev/null
	docker compose up -d ollama ollama-pull
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

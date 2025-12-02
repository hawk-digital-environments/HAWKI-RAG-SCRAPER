SITEMAP_PAGES ?= 6
SITEMAP_START ?= 1
SITEMAP_OUTPUT ?= /app/data/hawk_sitemap.json
SITEMAP_BASE ?= https://www.hawk.de/sitemaps/main/sitemap.xml

.PHONY: crawl-sitemap crawl-test crawl-full build up down logs

crawl-sitemap:
	docker compose run --rm crawler \
		python hawk_sitemap_scraper.py --hawk-sitemap \
		--base-url $(SITEMAP_BASE) \
		--start-page $(SITEMAP_START) \
		--pages $(SITEMAP_PAGES) \
		--output $(SITEMAP_OUTPUT)

crawl-test:
	curl -s -X POST http://localhost:8004/crawl \
		-H "Content-Type: application/json" \
		-d '{"url": "https://www.hawk.de", "max_pages": 100, "discovery_mode": true, "skip_images": true, "max_concurrency": 1, "max_rpm": 20}' \
		| python -m json.tool

crawl-full:
	curl -s -X POST http://localhost:8004/crawl \
		-H "Content-Type: application/json" \
		-d '{"url": "https://www.hawk.de", "max_pages": 100000, "discovery_mode": true, "skip_images": true, "max_concurrency": 2, "max_rpm": 30}' \
		| python -m json.tool

jobs:
	curl -s http://localhost:8004/jobs | python -m json.tool

cancel:
	@if [ -z "$(JOB_ID)" ]; then echo "Usage: make cancel JOB_ID=<id>"; exit 1; fi
	curl -s -X POST http://localhost:8004/jobs/$(JOB_ID)/cancel | python -m json.tool

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

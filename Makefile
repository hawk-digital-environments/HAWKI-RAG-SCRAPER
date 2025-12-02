SITEMAP_PAGES ?= 6
SITEMAP_START ?= 1
SITEMAP_OUTPUT ?= /app/data/hawk_sitemap.json
SITEMAP_BASE ?= https://www.hawk.de/sitemaps/main/sitemap.xml

.PHONY: crawl-up build up down logs

crawl-up:
	docker compose run --rm crawler \
		python hawk_sitemap_scraper.py --hawk-sitemap \
		--base-url $(SITEMAP_BASE) \
		--start-page $(SITEMAP_START) \
		--pages $(SITEMAP_PAGES) \
		--output $(SITEMAP_OUTPUT)

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

SITEMAP_PAGES ?= 6
SITEMAP_START ?= 1
SITEMAP_DIR ?= /app/shared/sitemaps
HAWK_SITEMAP_FILE ?= $(SITEMAP_DIR)/hawk_sitemap.json
SITEMAP_BASE ?= https://www.hawk.de/sitemaps/main/sitemap.xml
PROJEKT_BASE ?= https://projekte.g.hawk.de
PROJEKT_SITEMAP_JSON ?= https://projekte.g.hawk.de/sitemap.json
PROJEKT_SITEMAP_FILE ?= $(SITEMAP_DIR)/projekte_sitemap.json
PROJEKT_JOB_ID ?= Projekte_HAWK
CRAWL_TEST_JOB_ID ?= Test_HAWK
CRAWL_FULL_JOB_ID ?= Full_HAWK_23Jan
RESCRAPE_FAILED ?= false
FAILED_THRESHOLD ?= 100
MAX_RETRY_ROUNDS ?= 4
PYTHON ?= python3

# Allow `make cancel <job_id>` as shorthand
ifeq ($(firstword $(MAKECMDGOALS)),cancel)
  ifneq ($(word 2,$(MAKECMDGOALS)),)
    override JOB_ID := $(word 2,$(MAKECMDGOALS))
    $(eval $(word 2,$(MAKECMDGOALS)):=)
  endif
endif

# Allow `make clean-shared <job_id>` as shorthand
ifeq ($(firstword $(MAKECMDGOALS)),clean-shared)
  ifneq ($(word 2,$(MAKECMDGOALS)),)
    override JOB_ID := $(word 2,$(MAKECMDGOALS))
    $(eval $(word 2,$(MAKECMDGOALS)):=)
  endif
endif

.PHONY: crawl-sitemap crawl-test crawl-full crawl-projekt crawl-full-auto crawl-projekt-auto build up down logs clean-shared

crawl-sitemap:
	docker compose run --rm crawler \
		sh -lc 'mkdir -p $(SITEMAP_DIR) && \
		python -m src.crawler.core.sitemap_scraper --sitemap \
		--base-url $(SITEMAP_BASE) \
		--start-page $(SITEMAP_START) \
		--pages $(SITEMAP_PAGES) \
		--output $(HAWK_SITEMAP_FILE)'

crawl-test:
	$(MAKE) crawl-sitemap
	curl -s -X POST http://localhost:8040/crawl \
		-H "Content-Type: application/json" \
		-d '{"url": "https://www.hawk.de", "job_id":"$(CRAWL_TEST_JOB_ID)", "rescrape_failed": $(RESCRAPE_FAILED), "hawk_sitemap": true, "sitemap_base": "$(SITEMAP_BASE)", "sitemap_output": "$(HAWK_SITEMAP_FILE)", "max_pages": 100, "discovery_mode": true, "skip_images": true, "max_concurrency": 1, "max_rpm": 20}' \
		| $(PYTHON) -m json.tool

crawl-full:
	$(MAKE) crawl-sitemap
	curl -s -X POST http://localhost:8040/crawl \
		-H "Content-Type: application/json" \
		-d '{"url": "https://www.hawk.de","job_id":"$(CRAWL_FULL_JOB_ID)", "rescrape_failed": $(RESCRAPE_FAILED), "hawk_sitemap": true, "sitemap_base": "$(SITEMAP_BASE)", "sitemap_output": "$(HAWK_SITEMAP_FILE)", "max_pages": 40000, "discovery_mode": true, "skip_images": true, "max_concurrency": 3, "max_rpm": 40}' \
		| $(PYTHON) -m json.tool

crawl-full-auto:
	@round=0; \
	while [ $$round -lt $(MAX_RETRY_ROUNDS) ]; do \
		round=$$((round+1)); \
		if [ $$round -eq 1 ]; then \
			$(MAKE) crawl-full RESCRAPE_FAILED=false; \
		else \
			$(MAKE) crawl-full RESCRAPE_FAILED=true; \
		fi; \
		printf "Waiting for job %s to complete...\\n" "$(CRAWL_FULL_JOB_ID)"; \
		while true; do \
			status=$$(curl -s http://localhost:8040/jobs/$(CRAWL_FULL_JOB_ID) | $(PYTHON) -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))"); \
			if [ "$$status" = "completed" ]; then break; fi; \
			sleep 10; \
		done; \
		failed=$$(docker compose exec -T crawler python -c "import json; p='/app/shared/$(CRAWL_FULL_JOB_ID)/summary.json'; d=json.load(open(p)); print(d.get('urls',{}).get('failed',0))"); \
		printf "Round %s: failed URLs = %s\\n" "$$round" "$$failed"; \
		if [ "$$failed" -le "$(FAILED_THRESHOLD)" ]; then \
			echo "Stopping: failed URLs <= $(FAILED_THRESHOLD)"; \
			exit 0; \
		fi; \
	done; \
	echo "Stopping: reached max retry rounds ($(MAX_RETRY_ROUNDS)) with failed URLs still > $(FAILED_THRESHOLD)"; \
	exit 1

crawl-projekt:
	docker compose run --rm crawler \
		sh -lc 'mkdir -p $(SITEMAP_DIR) && curl -sSfL "$(PROJEKT_SITEMAP_JSON)" -o $(PROJEKT_SITEMAP_FILE)'
	curl -s -X POST http://localhost:8040/crawl \
		-H "Content-Type: application/json" \
		-d '{"url": "$(PROJEKT_SITEMAP_JSON)", "job_id":"$(PROJEKT_JOB_ID)", "rescrape_failed": $(RESCRAPE_FAILED), "max_pages": 2000, "discovery_mode": true, "skip_images": false, "max_concurrency": 3, "max_rpm": 50}' \
		| $(PYTHON) -m json.tool

crawl-projekt-auto:
	@round=0; \
	while [ $$round -lt $(MAX_RETRY_ROUNDS) ]; do \
		round=$$((round+1)); \
		if [ $$round -eq 1 ]; then \
			$(MAKE) crawl-projekt RESCRAPE_FAILED=false; \
		else \
			$(MAKE) crawl-projekt RESCRAPE_FAILED=true; \
		fi; \
		printf "Waiting for job %s to complete...\\n" "$(PROJEKT_JOB_ID)"; \
		while true; do \
			status=$$(curl -s http://localhost:8040/jobs/$(PROJEKT_JOB_ID) | $(PYTHON) -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))"); \
			if [ "$$status" = "completed" ]; then break; fi; \
			sleep 10; \
		done; \
		failed=$$(docker compose exec -T crawler python -c "import json; p='/app/shared/$(PROJEKT_JOB_ID)/summary.json'; d=json.load(open(p)); print(d.get('urls',{}).get('failed',0))"); \
		printf "Round %s: failed URLs = %s\\n" "$$round" "$$failed"; \
		if [ "$$failed" -le "$(FAILED_THRESHOLD)" ]; then \
			echo "Stopping: failed URLs <= $(FAILED_THRESHOLD)"; \
			exit 0; \
		fi; \
	done; \
	echo "Stopping: reached max retry rounds ($(MAX_RETRY_ROUNDS)) with failed URLs still > $(FAILED_THRESHOLD)"; \
	exit 1

jobs:
	curl -s http://localhost:8040/jobs | $(PYTHON) -m json.tool

cancel:
	@if [ -z "$(JOB_ID)" ]; then echo "Usage: make cancel JOB_ID=<id>  (or make cancel <id>)"; exit 1; fi
	curl -s -X POST http://localhost:8040/jobs/$(JOB_ID)/cancel | $(PYTHON) -m json.tool

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

clean-shared:
	@if [ -z "$(JOB_ID)" ]; then echo "Usage: make clean-shared JOB_ID=<id>"; exit 1; fi
	docker compose exec crawler sh -lc 'rm -rf /app/shared/$(JOB_ID)'

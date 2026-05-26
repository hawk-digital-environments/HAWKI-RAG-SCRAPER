SITEMAP_PAGES ?= 6
SITEMAP_START ?= 1
SITEMAP_DIR ?= /app/shared/sitemaps
SITE_PROFILE ?= /app/profiles/hawk.json
SITE_SITEMAP_FILE ?= $(SITEMAP_DIR)/site_sitemap.json
SITEMAP_BASE ?= https://www.hawk.de/sitemaps/main/sitemap.xml
URL ?= https://www.hawk.de
JSON_SITEMAP_URL ?= https://projekte.g.hawk.de/sitemap.json
JSON_SITEMAP_FILE ?= $(SITEMAP_DIR)/json_sitemap.json
JOB_ID_JSON_SITEMAP ?= JsonSitemap_Job
JOB_ID_SAMPLE ?= Site_Sample
JOB_ID_FULL ?= Site_Full
MAX_PAGES_SAMPLE ?= 100
MAX_PAGES_FULL ?=
CRAWL_SITE_MAX_PAGES ?= 40000
RESCRAPE_FAILED ?= false
FAILED_THRESHOLD ?= 100
MAX_RETRY_ROUNDS ?= 4
PYTHON ?= python3
DISCOVERY_MODE ?= false
SKIP_IMAGES ?= false

CRAWLER_HOST ?= http://localhost:8040

.DEFAULT_GOAL := help

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

.PHONY: crawl crawl-profile-sitemap crawl-sample crawl-site crawl-site-sitemap-only crawl-json-sitemap crawl-site-auto crawl-json-sitemap-auto build up down logs clean-shared audit-ui-fix start-ui ci-test

crawl:
	@set -e; \
		$(MAKE) crawl-profile-sitemap SITEMAP_PAGES=$(SITEMAP_PAGES); \
		sitemap_count=$$(docker compose exec -T crawler python3 -c "import json; from pathlib import Path; p = Path('$(SITE_SITEMAP_FILE)'); data = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}; print(len(data) if isinstance(data, dict) else 0)"); \
		echo "Sitemap URLs: $$sitemap_count"; \
		if [ "$$sitemap_count" -le 0 ]; then \
			echo "Stopping: sitemap is empty or missing at $(SITE_SITEMAP_FILE)"; \
			exit 1; \
		fi; \
		if [ -n "$(strip $(MAX_PAGES_FULL))" ]; then \
			effective_max_pages="$(MAX_PAGES_FULL)"; \
			effective_discovery_mode=true; \
			echo "Running crawl with explicit max_pages=$$effective_max_pages and discovery_mode=$$effective_discovery_mode"; \
		else \
			effective_max_pages="$$sitemap_count"; \
			effective_discovery_mode=false; \
			echo "Running crawl with sitemap-sized max_pages=$$effective_max_pages and discovery_mode=$$effective_discovery_mode"; \
		fi; \
		curl -s -X POST $(CRAWLER_HOST)/crawl \
			-H "Content-Type: application/json" \
			-d "{\"url\": \"$(URL)\", \"job_id\":\"$(JOB_ID_FULL)\", \"site_profile_path\":\"$(SITE_PROFILE)\", \"rescrape_failed\": $(RESCRAPE_FAILED), \"sitemap\": true, \"sitemap_base\": \"$(SITEMAP_BASE)\", \"sitemap_output\": \"$(SITE_SITEMAP_FILE)\", \"max_pages\": $$effective_max_pages, \"discovery_mode\": $$effective_discovery_mode, \"skip_images\": $(SKIP_IMAGES), \"max_concurrency\": 2, \"max_rpm\": 40}" \
			| $(PYTHON) -m json.tool

crawl-profile-sitemap:
	docker compose exec -T crawler \
		sh -lc 'mkdir -p $(SITEMAP_DIR) && \
		python -m hawki_crawler.crawler.sitemap.scraper --sitemap \
		--base-url $(SITEMAP_BASE) \
		--profile $(SITE_PROFILE) \
		--start-page $(SITEMAP_START) \
		--pages $(SITEMAP_PAGES) \
		--output $(SITE_SITEMAP_FILE)'

crawl-sample:
	curl -s -X POST $(CRAWLER_HOST)/crawl \
		-H "Content-Type: application/json" \
		-d '{"url": "https://www.hawk.de", "job_id":"$(JOB_ID_SAMPLE)", "site_profile_path":"$(SITE_PROFILE)", "rescrape_failed": $(RESCRAPE_FAILED), "sitemap": true, "sitemap_base": "$(SITEMAP_BASE)", "sitemap_output": "$(SITE_SITEMAP_FILE)", "max_pages": $(MAX_PAGES_SAMPLE), "discovery_mode": $(DISCOVERY_MODE), "skip_images": $(SKIP_IMAGES), "max_concurrency": 1, "max_rpm": 20}' \
		| $(PYTHON) -m json.tool

crawl-site:
	curl -s -X POST $(CRAWLER_HOST)/crawl \
		-H "Content-Type: application/json" \
		-d '{"url": "https://www.hawk.de","job_id":"$(JOB_ID_FULL)", "site_profile_path":"$(SITE_PROFILE)", "rescrape_failed": $(RESCRAPE_FAILED), "sitemap": true, "sitemap_base": "$(SITEMAP_BASE)", "sitemap_output": "$(SITE_SITEMAP_FILE)", "max_pages": $(if $(strip $(MAX_PAGES_FULL)),$(MAX_PAGES_FULL),$(CRAWL_SITE_MAX_PAGES)), "discovery_mode": $(DISCOVERY_MODE), "skip_images": $(SKIP_IMAGES), "max_concurrency": 2, "max_rpm": 40}' \
		| $(PYTHON) -m json.tool

crawl-site-sitemap-only:
	curl -s -X POST $(CRAWLER_HOST)/crawl \
		-H "Content-Type: application/json" \
		-d '{"url": "$(SITEMAP_BASE)","job_id":"$(JOB_ID_FULL)", "site_profile_path":"$(SITE_PROFILE)", "rescrape_failed": $(RESCRAPE_FAILED), "sitemap": true, "sitemap_base": "$(SITEMAP_BASE)", "sitemap_output": "$(SITE_SITEMAP_FILE)", "sitemap_only": true, "discovery_mode": false, "max_pages": 0, "skip_images": $(SKIP_IMAGES), "max_concurrency": 2, "max_rpm": 40}' \
		| $(PYTHON) -m json.tool

crawl-site-auto:
	@round=0; \
	while [ $$round -lt $(MAX_RETRY_ROUNDS) ]; do \
		round=$$((round+1)); \
		if [ $$round -eq 1 ]; then \
			$(MAKE) crawl-site RESCRAPE_FAILED=false; \
		else \
			$(MAKE) crawl-site RESCRAPE_FAILED=true; \
		fi; \
		printf "Waiting for job %s to complete...\\n" "$(JOB_ID_FULL)"; \
		while true; do \
			status=$$(curl -s $(CRAWLER_HOST)/jobs/$(JOB_ID_FULL) | $(PYTHON) -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))"); \
			if [ "$$status" = "completed" ]; then break; fi; \
			sleep 10; \
		done; \
		failed=$$(docker compose exec -T crawler python -c "import json; p='/app/shared/$(JOB_ID_FULL)/summary.json'; d=json.load(open(p)); print(d.get('urls',{}).get('failed',0))"); \
		printf "Round %s: failed URLs = %s\\n" "$$round" "$$failed"; \
		if [ "$$failed" -le "$(FAILED_THRESHOLD)" ]; then \
			echo "Stopping: failed URLs <= $(FAILED_THRESHOLD)"; \
			exit 0; \
		fi; \
	done; \
	echo "Stopping: reached max retry rounds ($(MAX_RETRY_ROUNDS)) with failed URLs still > $(FAILED_THRESHOLD)"; \
	exit 1

crawl-json-sitemap:
	docker compose run --rm crawler \
		sh -lc 'mkdir -p $(SITEMAP_DIR) && curl -sSfL "$(JSON_SITEMAP_URL)" -o $(JSON_SITEMAP_FILE)'
	curl -s -X POST $(CRAWLER_HOST)/crawl \
		-H "Content-Type: application/json" \
		-d '{"url": "$(JSON_SITEMAP_URL)", "job_id":"$(JOB_ID_JSON_SITEMAP)", "rescrape_failed": $(RESCRAPE_FAILED), "max_pages": 6000, "discovery_mode": false, "skip_images": false, "max_concurrency": 2, "max_rpm": 40}' \
		| $(PYTHON) -m json.tool

crawl-json-sitemap-auto:
	@round=0; \
	while [ $$round -lt $(MAX_RETRY_ROUNDS) ]; do \
		round=$$((round+1)); \
		if [ $$round -eq 1 ]; then \
			$(MAKE) crawl-json-sitemap RESCRAPE_FAILED=false; \
		else \
			$(MAKE) crawl-json-sitemap RESCRAPE_FAILED=true; \
		fi; \
		printf "Waiting for job %s to complete...\\n" "$(JOB_ID_JSON_SITEMAP)"; \
		while true; do \
			status=$$(curl -s $(CRAWLER_HOST)/jobs/$(JOB_ID_JSON_SITEMAP) | $(PYTHON) -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))"); \
			if [ "$$status" = "completed" ]; then break; fi; \
			sleep 10; \
		done; \
		failed=$$(docker compose exec -T crawler python -c "import json; p='/app/shared/$(JOB_ID_JSON_SITEMAP)/summary.json'; d=json.load(open(p)); print(d.get('urls',{}).get('failed',0))"); \
		printf "Round %s: failed URLs = %s\\n" "$$round" "$$failed"; \
		if [ "$$failed" -le "$(FAILED_THRESHOLD)" ]; then \
			echo "Stopping: failed URLs <= $(FAILED_THRESHOLD)"; \
			exit 0; \
		fi; \
	done; \
	echo "Stopping: reached max retry rounds ($(MAX_RETRY_ROUNDS)) with failed URLs still > $(FAILED_THRESHOLD)"; \
	exit 1

jobs:
	curl -s $(CRAWLER_HOST)/jobs | $(PYTHON) -m json.tool

cancel:
	@if [ -z "$(JOB_ID)" ]; then echo "Usage: make cancel JOB_ID=<id>  (or make cancel <id>)"; exit 1; fi
	curl -s -X POST $(CRAWLER_HOST)/jobs/$(JOB_ID)/cancel | $(PYTHON) -m json.tool

build:
	docker compose build

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

audit-ui-fix:
	@set -e; \
		echo "Running npm audit fix in ui/"; \
		if npm audit fix --prefix ui; then \
			exit 0; \
		fi; \
		echo "npm audit fix left advisories; checking production dependencies before continuing"; \
		npm audit --omit=dev --prefix ui

start-ui:
	npm install --prefix ui
	$(MAKE) audit-ui-fix
	npm --prefix ui run dev

clean-shared:
	@if [ -z "$(JOB_ID)" ]; then echo "Usage: make clean-shared JOB_ID=<id>"; exit 1; fi
	docker compose exec crawler sh -lc 'rm -rf /app/shared/$(JOB_ID)'

ci-test:
	docker build --target test -t crawler-test . && docker run crawler-test 

help:
	@echo "COMMAND             DESCRIPTION"
	@echo "------------------------------------------------------------"
	@printf "%-20s %s\n" "crawl-sitemap"       "To run crawler service against a site map."
	@printf "%-20s %s\n" "crawl-test"          "Send test command to crawler service."
	@printf "%-20s %s\n" "crawl-full"          "TODO: explain"
	@printf "%-20s %s\n" "crawl-project"       "Display this help message"
	@printf "%-20s %s\n" "jobs"                "Display all jobs"
	@printf "%-20s %s\n" "cancel"              "Cancel a job via 'JOB_ID' variable."
	@printf "%-20s %s\n" "build"               "Build the crawler service."
	@printf "%-20s %s\n" "up"                  "Start the crawler service."
	@printf "%-20s %s\n" "down"                "Stop the crawler service without removing volumes."
	@printf "%-20s %s\n" "teardown"            "Teardown compose project and remove all connected resources."
	@printf "%-20s %s\n" "logs"                "Show live service logs."
	@printf "%-20s %s\n" "virtualenv"          "Setup virtualenv."
	@printf "%-20s %s\n" "setup"               "Setup requirements"
	@printf "%-20s %s\n" "ci-test"             "To run ci tests"
	@printf "%-20s %s\n" "help"                "Display this help message"

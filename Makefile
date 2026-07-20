# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
# Override any value at runtime, for example:
#   make crawl SITE_PROFILE=/var/www/html/profiles/custom.json
#   make crawl MAX_PAGES_FULL=1000 DISCOVERY_MODE=true

# Sitemap settings used by the crawler service when `make crawl` is run.
SITEMAP_PAGES ?= 6
SITEMAP_START ?= 1
SITEMAP_DIR ?= /var/www/html/shared/sitemaps
SITEMAP_BASE ?= https://www.hawk.de/sitemaps/main/sitemap.xml
SITE_SITEMAP_FILE ?= $(SITEMAP_DIR)/site_sitemap.json

# Site crawl settings.
URL ?= https://www.hawk.de
SITE_PROFILE ?= /var/www/html/profiles/hawk.json
MAX_PAGES_FULL ?=
CRAWL_SITE_MAX_PAGES ?= 40000
DISCOVERY_MODE ?= false
SKIP_IMAGES ?= false

# Stable job name makes it easy to check, cancel, or clean a run.
JOB_ID_FULL ?= Site_Full

# Retry behavior for rerunning `make crawl` against failed URLs.
RESCRAPE_FAILED ?= false

# Local tooling and service endpoints.
PYTHON ?= python3
CRAWLER_HOST ?= http://localhost:8041

.DEFAULT_GOAL := help

# -----------------------------------------------------------------------------
# Shorthand Arguments
# -----------------------------------------------------------------------------
# Let users write `make cancel <job_id>` instead of `make cancel JOB_ID=<job_id>`.
ifeq ($(firstword $(MAKECMDGOALS)),cancel)
  ifneq ($(word 2,$(MAKECMDGOALS)),)
    override JOB_ID := $(word 2,$(MAKECMDGOALS))
    $(eval $(word 2,$(MAKECMDGOALS)):=)
  endif
endif

# Let users write `make clean-shared <job_id>` instead of
# `make clean-shared JOB_ID=<job_id>`.
ifeq ($(firstword $(MAKECMDGOALS)),clean-shared)
  ifneq ($(word 2,$(MAKECMDGOALS)),)
    override JOB_ID := $(word 2,$(MAKECMDGOALS))
    $(eval $(word 2,$(MAKECMDGOALS)):=)
  endif
endif

.PHONY: \
	crawl \
	jobs \
	cancel \
	build \
	up \
	down \
	logs \
	audit-ui-fix \
	start-ui \
	clean-shared \
	ci-test \
	help

# -----------------------------------------------------------------------------
# Crawl Workflows
# -----------------------------------------------------------------------------

# Full recommended crawl. The API service handles sitemap scraping/loading when
# `sitemap` is true, so this target only submits the job.
crawl:
	curl -s -X POST $(CRAWLER_HOST)/crawl \
		-H "Content-Type: application/json" \
		-d '{"url": "$(URL)", "job_id":"$(JOB_ID_FULL)", "site_profile_path":"$(SITE_PROFILE)", "rescrape_failed": $(RESCRAPE_FAILED), "sitemap": true, "sitemap_base": "$(SITEMAP_BASE)", "sitemap_output": "$(SITE_SITEMAP_FILE)", "sitemap_start_page": $(SITEMAP_START), "sitemap_pages": $(SITEMAP_PAGES), "max_pages": $(if $(strip $(MAX_PAGES_FULL)),$(MAX_PAGES_FULL),$(CRAWL_SITE_MAX_PAGES)), "discovery_mode": $(DISCOVERY_MODE), "skip_images": $(SKIP_IMAGES), "max_concurrency": 2, "max_rpm": 40}' \
		| $(PYTHON) -m json.tool

# -----------------------------------------------------------------------------
# Job Controls
# -----------------------------------------------------------------------------

# List all crawler jobs reported by the API.
jobs:
	curl -s $(CRAWLER_HOST)/jobs | $(PYTHON) -m json.tool

# Cancel a running job. Usage:
#   make cancel JOB_ID=<job_id>
#   make cancel <job_id>
cancel:
	@if [ -z "$(JOB_ID)" ]; then echo "Usage: make cancel JOB_ID=<id>  (or make cancel <id>)"; exit 1; fi
	curl -s -X POST $(CRAWLER_HOST)/jobs/$(JOB_ID)/cancel | $(PYTHON) -m json.tool

# -----------------------------------------------------------------------------
# Services
# -----------------------------------------------------------------------------

# Build the Docker image for the crawler service.
build:
	docker compose build

# Build and start the containerized crawler API and production UI.
up:
	docker compose up --build -d
	@echo "UI available at http://localhost:8041/ui/"

# Stop and remove Docker Compose containers and networks for this project.
down:
	docker compose down

# Follow Docker Compose logs for all services.
logs:
	docker compose logs -f

# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------

# Run npm audit fix for the UI. If dev-only advisories remain, allow the command
# to continue only when production dependencies pass audit.
audit-ui-fix:
	@set -e; \
		echo "Running npm audit fix in ui/"; \
		if npm audit fix --prefix ui; then \
			exit 0; \
		fi; \
		echo "npm audit fix left advisories; checking production dependencies before continuing"; \
		npm audit --omit=dev --prefix ui

# Install UI dependencies, generate SvelteKit files, then start the UI dev
# server. Polling avoids Linux inotify watcher exhaustion on busy workstations.
# CRAWLER_API_BASE_URL defaults to the local crawler API unless overridden.
start-ui:
	npm install --prefix ui
	$(MAKE) audit-ui-fix
	npm --prefix ui exec svelte-kit sync
	CHOKIDAR_USEPOLLING=$${CHOKIDAR_USEPOLLING:-true} CRAWLER_API_BASE_URL=$${CRAWLER_API_BASE_URL:-http://127.0.0.1:8041} PUBLIC_API_BASE_URL=$${PUBLIC_API_BASE_URL:-} npm --prefix ui run dev

# -----------------------------------------------------------------------------
# Maintenance and Tests
# -----------------------------------------------------------------------------

# Remove shared crawl output for one job from the crawler container.
# Usage:
#   make clean-shared JOB_ID=<job_id>
#   make clean-shared <job_id>
clean-shared:
	@if [ -z "$(JOB_ID)" ]; then echo "Usage: make clean-shared JOB_ID=<id>"; exit 1; fi
	docker compose exec crawler sh -lc 'rm -rf /var/www/html/shared/$(JOB_ID)'

# Build the test image and run the containerized test suite.
ci-test:
	docker build --target test -t crawler-test . && docker run crawler-test 

# -----------------------------------------------------------------------------
# Help
# -----------------------------------------------------------------------------

# Print a human-readable command reference. This is the default target.
help:
	@echo "COMMAND                     DESCRIPTION"
	@echo "----------------------------------------------------------------------"
	@printf "%-28s %s\n" "crawl"                    "Submit the sitemap-backed site crawl."
	@printf "%-28s %s\n" "jobs"                     "Display all jobs."
	@printf "%-28s %s\n" "cancel"                   "Cancel a job: make cancel <job_id> or make cancel JOB_ID=<id>."
	@printf "%-28s %s\n" "clean-shared"             "Remove shared data for a job: make clean-shared <job_id>."
	@printf "%-28s %s\n" "build"                    "Build the crawler service."
	@printf "%-28s %s\n" "up"                       "Build and start the containerized API and UI."
	@printf "%-28s %s\n" "down"                     "Stop the crawler service."
	@printf "%-28s %s\n" "logs"                     "Show live service logs."
	@printf "%-28s %s\n" "start-ui"                 "Install deps, audit fix, and start UI dev server."
	@printf "%-28s %s\n" "audit-ui-fix"             "Run npm audit fix in ui/."
	@printf "%-28s %s\n" "ci-test"                  "Run CI tests in Docker."
	@printf "%-28s %s\n" "help"                     "Display this help message."

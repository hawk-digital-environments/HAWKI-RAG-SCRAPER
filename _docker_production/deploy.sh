#!/bin/bash
# Deploys the HAWKI RAG Scraper production stack: pulls the image pinned
# through HAWKI_RAG_SCRAPER_VERSION in .env and starts the scraper service.
#
# There are no migrations or sidecar services to wait for: the scraper image
# is self-contained (nginx + gunicorn + the SvelteKit frontend server + the
# Playwright chromium browser), so a single "docker compose up" brings the
# whole stack up.

docker compose up --pull always -d

# Stop if the previous command failed
if [ $? -ne 0 ]; then
    echo "Docker compose up failed"
    exit 1
fi

# Multi-stage build for optimized Docker image.
# NOTE: all CI pipelines (publish-version.yml, deploy-scraper-prod.yml,
# deploy-scraper-testing.yml) build this file WITHOUT a --target, so the
# production stage must remain the LAST stage in this file.
FROM neunerlei/python-nginx:3.13 AS base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies required for Playwright and crawl4ai.
# BuildKit cache mounts keep the apt state out of the image layers and speed
# up rebuilds - the cleanup commands are intentionally omitted, as they would
# wipe the shared cache.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    # Build essentials
    build-essential \
    ca-certificates \
    curl \
    wget \
    # Playwright browser dependencies
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    # Additional dependencies
    fonts-liberation \
    libappindicator3-1 \
    xdg-utils \
    libxml2-dev \
    libxslt1-dev \
    # Add mime types like docx etc 
    media-types


FROM base AS development

ARG USERNAME=dev
ARG USER_UID=1000
ARG USER_GID=$USER_UID

COPY --from=ghcr.io/astral-sh/uv:0.11.15 /uv /uvx /usr/local/bin/

RUN --mount=type=cache,target=/root/.cache \
    pip3 install pipx && python3 -m pipx ensurepath

# Install sudo and create user
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install -y sudo \
    && groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME \
    && echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME

WORKDIR /workspace

USER $USERNAME

ENV NVM_DIR=/home/${USERNAME}/.nvm

RUN mkdir -p $NVM_DIR \
    && curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash

# Make nvm available in future shells
RUN echo 'export NVM_DIR="$HOME/.nvm"' >> /home/${USERNAME}/.bashrc \
    && echo '[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"' >> /home/${USERNAME}/.bashrc \
    && echo '[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"' >> /home/${USERNAME}/.bashrc



FROM base AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.15 /uv /uvx /usr/local/bin/

WORKDIR /build
COPY pyproject.toml uv.lock README.md ./
COPY hawki_crawler ./hawki_crawler

# Neunerlei build mode: sets up the same derived environment the production
# image will have (venv wrapper, exported vars) for the build steps below.
RUN /container/entrypoint/entrypoint.sh

RUN --mount=type=cache,target=/root/.cache \
    uv build


FROM base AS test

USER root

COPY --from=ghcr.io/astral-sh/uv:0.11.15 /uv /uvx /usr/local/bin/

WORKDIR /tests

COPY pyproject.toml uv.lock README.md ./
COPY hawki_crawler ./hawki_crawler
COPY tests tests

# Neunerlei build mode: same derived environment as the production image.
RUN /container/entrypoint/entrypoint.sh

RUN --mount=type=cache,target=/root/.cache \
    uv sync --all-groups
RUN --mount=type=cache,target=/root/.cache \
    --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    uv run playwright install --with-deps chromium

CMD ["uv", "run", "--no-sync", "pytest", "-vvv"]
ENTRYPOINT []


FROM node:22-slim AS ui-builder

# SvelteKit/Vite inline PUBLIC_* values into the bundle at BUILD time: this
# value drives kit.paths.base (ui/svelte.config.js) and $env/static/public
# consumers. Pass this build arg to serve the UI under a different path
# (see the deploy workflows); the default matches the runtime default in
# docker/custom/env/10-service.env.
ARG PUBLIC_API_BASE_URL=/ui

WORKDIR /build
COPY ui/package.json ui/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci
COPY ui/ .
RUN echo "PUBLIC_API_BASE_URL=${PUBLIC_API_BASE_URL}" > .env.production \
    && npm run build && npm prune --production


FROM base AS production

WORKDIR /var/www/html

COPY --from=builder --chown=www-data:www-data /build/dist/*.whl .

RUN --mount=type=cache,target=/var/www/.cache,uid=33,gid=33 \
    gosu www-data python -m pip install *.whl && rm *.whl

# Playwright system dependencies, resolved per platform (also correct for
# the linux/arm64 builds of the public image).
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    python -m playwright install-deps chromium
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
# The browsers ship inside the image, so this download must NOT be cache
# mounted. o+rX keeps them usable even when PUID/PGID move www-data away
# from uid 33 at runtime.
RUN python -m playwright install chromium \
    && chown -R www-data:www-data /opt/ms-playwright \
    && chmod -R o+rX /opt/ms-playwright

RUN mkdir -p /var/www/html/output /var/www/html/shared \
    && chown -R www-data:www-data /var/www/html/output /var/www/html/shared

# Runtime node binary: exactly the binary that built the UI, copied from the
# ui-builder stage (replaces the previous nvm download; npm is not needed at
# runtime).
COPY --from=ui-builder /usr/local/bin/node /usr/local/bin/node

COPY --from=ui-builder --chown=www-data:www-data /build/build /var/www/html/ui/build
COPY --from=ui-builder --chown=www-data:www-data /build/package.json /var/www/html/ui/package.json
COPY --from=ui-builder --chown=www-data:www-data /build/node_modules /var/www/html/ui/node_modules

# Service-level runtime defaults (CRAWLER_API_BASE_URL, ORIGIN,
# NODE_SERVICE_PORT, PUBLIC_API_BASE_URL) live in docker/custom/env and can
# be overridden per deployment without a rebuild.
COPY docker/custom /container/custom

ENV PYTHON_APP_MODULE="hawki_crawler.app.main:app"
ENV GUNICORN_WORKER_CLASS="uvicorn.workers.UvicornWorker"
ENV GUNICORN_WORKERS=1
# Chromium (Playwright) runs as www-data and needs a writable HOME for its
# user-data-dir; the base image has no usable home directory for www-data.
ENV HOME=/tmp

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:80/health || exit 1

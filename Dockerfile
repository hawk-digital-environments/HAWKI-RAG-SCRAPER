# Multi-stage build for optimized Docker image
FROM neunerlei/python-nginx:3.14 AS base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies required for Playwright and crawl4ai
RUN apt-get update && apt-get install -y --no-install-recommends \
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
    media-types \
    && rm -rf /var/lib/apt/lists/*


FROM base AS development

ARG USERNAME=dev
ARG USER_UID=1000
ARG USER_GID=$USER_UID

COPY --from=ghcr.io/astral-sh/uv:0.11.15 /uv /uvx /usr/local/bin/

RUN pip3 install pipx && python3 -m pipx ensurepath

# Install sudo and create user
RUN apt-get update \
    && apt-get install -y sudo \
    && groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME \
    && echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

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
RUN uv build


FROM base AS test

USER root

COPY --from=ghcr.io/astral-sh/uv:0.11.15 /uv /uvx /usr/local/bin/

WORKDIR /tests

COPY pyproject.toml uv.lock README.md ./
COPY hawki_crawler ./hawki_crawler
COPY tests tests

RUN uv sync --all-groups
RUN uv run playwright install --with-deps chromium

CMD ["uv", "run", "--no-sync", "pytest", "-vvv"]
ENTRYPOINT []


FROM node:22-slim AS ui-builder

WORKDIR /build
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ .
RUN echo "PUBLIC_API_BASE_URL=/ui" > .env.production \
    && npm run build && npm prune --production


FROM base AS production

WORKDIR /var/www/html

COPY --from=builder --chown=www-data:www-data /build/dist/*.whl .

RUN gosu www-data python -m pip install *.whl && rm *.whl

RUN python -m playwright install-deps chromium
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN python -m playwright install chromium \
    && chown -R www-data:www-data /opt/ms-playwright

RUN mkdir -p /var/www/html/output /var/www/html/shared \
    && chown -R www-data:www-data /var/www/html/output /var/www/html/shared

COPY ui/.nvmrc /tmp/ui-nvmrc
ENV NVM_DIR=/opt/nvm
RUN mkdir -p $NVM_DIR \
    && curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash \
    && . "$NVM_DIR/nvm.sh" \
    && nvm install "$(cat /tmp/ui-nvmrc)" \
    && ln -sf "$(dirname "$(nvm which current)")/node" /usr/local/bin/node \
    && ln -sf "$(dirname "$(nvm which current)")/npm" /usr/local/bin/npm \
    && rm /tmp/ui-nvmrc

COPY --from=ui-builder --chown=www-data:www-data /build/build /var/www/html/ui/build
COPY --from=ui-builder --chown=www-data:www-data /build/package.json /var/www/html/ui/package.json
COPY --from=ui-builder --chown=www-data:www-data /build/node_modules /var/www/html/ui/node_modules

COPY docker/custom /container/custom

ENV PYTHON_APP_MODULE="hawki_crawler.app.main:app"
ENV GUNICORN_WORKER_CLASS="uvicorn.workers.UvicornWorker"
ENV HOME=/tmp
ENV GUNICORN_WORKERS=1

ENV CRAWLER_API_BASE_URL=http://localhost:80
ENV NODE_SERVICE_PORT=3000
ENV ORIGIN=http://localhost:80

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:80/health || exit 1

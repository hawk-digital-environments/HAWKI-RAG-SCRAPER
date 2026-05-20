# Multi-stage build for optimized Docker image
FROM python:3.11-slim as base

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
    # Add mime types like docx etc 
    media-types \
    && rm -rf /var/lib/apt/lists/*


FROM base as development

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


FROM base as test

WORKDIR /tests

COPY --from=ghcr.io/astral-sh/uv:0.11.15 /uv /uvx /usr/local/bin/

COPY pyproject.toml uv.lock .

RUN uv venv && uv sync --all-groups
RUN uv run playwright install --with-deps chromium

COPY src ./src
COPY tests tests

ENV PYTHONPATH="/tests:${PYTHONPATH}"

CMD ["uv", "run", "pytest", "-vvv"]


FROM development as requirements

USER root

WORKDIR /build-requirements
COPY pyproject.toml uv.lock .
RUN uv export --no-dev --no-hashes --no-emit-project -o requirements.txt > requirements.txt


FROM base as production

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY --from=requirements /build-requirements/requirements.txt requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install --with-deps chromium

# Copy application code
COPY src/ ./src/

# Ensure src is on PYTHONPATH for runtime
ENV PYTHONPATH="/app/src:${PYTHONPATH}"

# Create output directory
RUN mkdir -p /app/output && chmod 755 /app/output

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

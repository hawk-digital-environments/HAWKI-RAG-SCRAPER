#!/usr/bin/env bash

set -euo pipefail

APP_MODULE="${APP_MODULE:-hawki_crawler.app.main:app}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
DATA_PATH="${DATA_PATH:-$(pwd)/output/shared}"

echo "========================================="
echo "Starting Crawl4AI FastAPI Server"
echo "========================================="

mkdir -p "$DATA_PATH"
export DATA_PATH

if command -v uv >/dev/null 2>&1; then
    echo "Installing dependencies with uv..."
    uv sync --all-groups

    echo "Installing Playwright Chromium..."
    uv run playwright install chromium

    echo ""
    echo "========================================="
    echo "Server starting on http://localhost:${PORT}"
    echo "API Documentation: http://localhost:${PORT}/docs"
    echo "Data path: ${DATA_PATH}"
    echo "========================================="
    echo ""

    exec uv run --no-sync uvicorn "$APP_MODULE" --host "$HOST" --port "$PORT" --reload
fi

echo "uv not found; using env/ virtual environment fallback."

if [ ! -d "env" ]; then
    echo "Creating virtual environment..."
    python3 -m venv env
fi

echo "Activating virtual environment..."
source env/bin/activate

echo "Installing dependencies with pip..."
python -m pip install -q --upgrade pip
python -m pip install -q -e .

echo "Installing Playwright Chromium..."
python -m playwright install chromium

echo ""
echo "========================================="
echo "Server starting on http://localhost:${PORT}"
echo "API Documentation: http://localhost:${PORT}/docs"
echo "Data path: ${DATA_PATH}"
echo "========================================="
echo ""

exec python -m uvicorn "$APP_MODULE" --host "$HOST" --port "$PORT" --reload

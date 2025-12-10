#!/bin/bash

# Start script for Crawl4AI FastAPI Server

echo "========================================="
echo "Starting Crawl4AI FastAPI Server"
echo "========================================="

# Check if virtual environment exists
if [ ! -d "env" ]; then
    echo "Creating virtual environment..."
    python3 -m venv env
fi

# Activate virtual environment
echo "Activating virtual environment..."
source env/bin/activate

# Install/upgrade dependencies
echo "Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# Install playwright browsers if not already installed
if [ ! -d "$HOME/.cache/ms-playwright" ]; then
    echo "Installing Playwright browsers..."
    playwright install chromium
fi

# Start the server
echo ""
echo "========================================="
echo "Server starting on http://localhost:8000"
echo "API Documentation: http://localhost:8000/docs"
echo "========================================="
echo ""

uvicorn main:app --host 0.0.0.0 --port 8000 --reload

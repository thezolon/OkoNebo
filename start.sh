#!/bin/bash
# Quick start script for the weather app

cd "$(dirname "$0")"

# Activate or create venv if needed
if [ ! -d "venv" ]; then
    echo "Creating virtualenv..."
    python3 -m venv venv
fi

source venv/bin/activate

# Load optional local environment overrides (API keys, etc.)
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# Install/update dependencies quietly
pip install -q -r requirements.txt 2>/dev/null

echo "Starting Weather App..."
echo "Browser: http://localhost:8888"
echo "API Docs: http://localhost:8888/docs"
echo "OpenAPI Spec: http://localhost:8888/openapi.json"
echo ""
echo "Press Ctrl+C to stop"
echo ""

uvicorn app.main:app --host 0.0.0.0 --port 8888 --reload

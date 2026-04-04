#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required but was not found in PATH."
    exit 1
fi

if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
else
    echo "Docker Compose is required but was not found."
    exit 1
fi

echo "Deploying Weather App on this host..."
echo "Using compose command: ${COMPOSE_CMD[*]}"

"${COMPOSE_CMD[@]}" up -d --build

echo
echo "Running health check..."
bash "$ROOT_DIR/health-check.sh"

echo
echo "Deployment complete."
echo "UI: http://localhost:8888"
echo "Swagger: http://localhost:8888/docs"
echo "Debug: http://localhost:8888/api/debug"

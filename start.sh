#!/usr/bin/env bash
# start.sh — start OkoNebo (Linux / macOS)
# Requires: Docker with the Compose plugin (docker compose)
# No Python required on the host.

set -euo pipefail
cd "$(dirname "$0")"

# Touch persistence files so Docker bind-mounts get regular files, not dirs.
touch secure_settings.db cache.db

echo "Starting OkoNebo..."
docker compose up -d --build --remove-orphans

echo ""
echo "  Dashboard : http://localhost:8888"
echo "  API docs  : http://localhost:8888/docs"
echo ""

# Health check with retries
for attempt in 1 2 3 4 5; do
    if bash health-check.sh 2>/dev/null; then
        exit 0
    fi
    echo "Waiting for container to be ready (attempt ${attempt}/5)..."
    sleep 3
done

echo "Container did not become healthy in time. Check logs:"
echo "  docker compose logs okonebo"
exit 1

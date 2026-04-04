#!/usr/bin/env bash
# scripts/reset.sh — factory-reset OkoNebo state files
#
# Normal rebuilds (docker compose up -d --build) preserve all state.
# Run THIS script only when you want to start completely fresh.
#
# What is removed:
#   secure_settings.db  — api keys, location, first-run flag, auth users
#   cache.db            — cached weather API responses
#
# What is NOT touched (unless --config is passed):
#   config.yaml         — base location / timezone / static options
#   .env                — environment variables / credentials
#
# Usage:
#   bash scripts/reset.sh              # wipe DBs only
#   bash scripts/reset.sh --config     # wipe DBs + config.yaml (full blank slate)
#   bash scripts/reset.sh --yes        # skip confirmation prompt

set -euo pipefail

WIPE_CONFIG=false
SKIP_CONFIRM=false

for arg in "$@"; do
    case "$arg" in
        --config) WIPE_CONFIG=true ;;
        --yes)    SKIP_CONFIRM=true ;;
        *)
            echo "Unknown option: $arg"
            echo "Usage: $0 [--config] [--yes]"
            exit 1
            ;;
    esac
done

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo ""
echo "OkoNebo factory reset"
echo "====================="
echo "  secure_settings.db  → will be removed"
echo "  cache.db            → will be removed"
if $WIPE_CONFIG; then
    echo "  config.yaml         → will be removed (--config)"
fi
echo ""

if ! $SKIP_CONFIRM; then
    read -r -p "Are you sure? This cannot be undone. (yes/N): " confirm
    if [[ "$confirm" != "yes" ]]; then
        echo "Aborted."
        exit 0
    fi
fi

echo "[reset] stopping container..."
docker compose -f "$PROJECT_ROOT/docker-compose.yml" down 2>/dev/null || true

echo "[reset] removing state files..."
rm -f "$PROJECT_ROOT/secure_settings.db"
rm -f "$PROJECT_ROOT/cache.db"

if $WIPE_CONFIG; then
    rm -f "$PROJECT_ROOT/config.yaml"
    echo "[reset] config.yaml removed"
fi

# Re-create empty placeholder files so Docker bind-mounts
# get regular files (not directories) on next start.
touch "$PROJECT_ROOT/secure_settings.db"
touch "$PROJECT_ROOT/cache.db"

echo "[reset] done — run 'docker compose up -d --build' to start fresh"

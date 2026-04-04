#!/usr/bin/env bash
# scripts/backup.sh [output-dir]
# Creates a timestamped backup of runtime state files.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-${ROOT_DIR}/backups}"
TS="$(date +%Y%m%d-%H%M%S)"
DEST="${OUT_DIR}/okonebo-backup-${TS}"

mkdir -p "${DEST}"

for f in config.yaml secure_settings.db cache.db .env; do
    if [[ -f "${ROOT_DIR}/${f}" ]]; then
        cp "${ROOT_DIR}/${f}" "${DEST}/${f}"
    fi
done

# Manifest for quick inspection
{
    echo "backup_created_at=${TS}"
    echo "source_root=${ROOT_DIR}"
    ls -1 "${DEST}" | sed 's/^/file=/'
} > "${DEST}/manifest.txt"

echo "Backup written to: ${DEST}"
ls -1 "${DEST}"

#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
DIST_DIR="$ROOT_DIR/dist"
STAMP="$(date +%Y%m%d-%H%M%S)"
PKG_NAME="weatherapp-pi-release-$STAMP"
STAGE_DIR="$DIST_DIR/$PKG_NAME"
ARCHIVE_PATH="$DIST_DIR/$PKG_NAME.tar.gz"
CHECKSUM_PATH="$ARCHIVE_PATH.sha256"

mkdir -p "$DIST_DIR"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"

copy_path() {
    local path="$1"
    cp -R "$ROOT_DIR/$path" "$STAGE_DIR/$path"
}

copy_path "app"
copy_path ".dockerignore"
copy_path "Dockerfile"
copy_path "docker-compose.yml"
copy_path "config.yaml"
copy_path "requirements.txt"
copy_path ".env.example"
copy_path "health-check.sh"
copy_path "deploy-on-pi.sh"
copy_path "start.sh"
copy_path "scripts"
copy_path "README.md"
copy_path "IMPLEMENTATION.md"
copy_path "RASPBERRY_PI_DEPLOYMENT.md"
copy_path "ROBUSTNESS_PLAN.md"

cat > "$STAGE_DIR/RELEASE_MANIFEST.txt" <<'EOF'
Weather App Raspberry Pi Release Package

Contents:
- app/
- .dockerignore
- Dockerfile
- docker-compose.yml
- config.yaml
- requirements.txt
- .env.example
- health-check.sh
- deploy-on-pi.sh
- start.sh
- scripts/
- README.md
- IMPLEMENTATION.md
- RASPBERRY_PI_DEPLOYMENT.md
- ROBUSTNESS_PLAN.md

Quick start on target:
1. tar -xzf weatherapp-pi-release-*.tar.gz
2. cd weatherapp-pi-release-*
3. bash deploy-on-pi.sh
EOF

chmod +x "$STAGE_DIR/health-check.sh"
chmod +x "$STAGE_DIR/deploy-on-pi.sh"
chmod +x "$STAGE_DIR/start.sh"
chmod +x "$STAGE_DIR/scripts/setup_wizard.py"
chmod +x "$STAGE_DIR/scripts/security_check.py"

if curl -fsS "http://localhost:8888/api/debug" >/dev/null 2>&1; then
    echo "Running secret leak check against http://localhost:8888 ..."
    python3 "$ROOT_DIR/scripts/security_check.py"
else
    echo "Skipping secret leak check (app not reachable at http://localhost:8888)."
fi

find "$STAGE_DIR" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$STAGE_DIR" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

tar -C "$DIST_DIR" -czf "$ARCHIVE_PATH" "$PKG_NAME"
sha256sum "$ARCHIVE_PATH" > "$CHECKSUM_PATH"
rm -rf "$STAGE_DIR"

echo "Release archive created: $ARCHIVE_PATH"
echo "Checksum written: $CHECKSUM_PATH"

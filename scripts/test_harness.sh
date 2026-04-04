#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv-test"
PY_BIN="${VENV_DIR}/bin/python"
PIP_BIN="${VENV_DIR}/bin/pip"
BASE_URL="${WEATHERAPP_BASE_URL:-http://localhost:8888}"
SKIP_DOCKER="${HARNESS_SKIP_DOCKER:-0}"

cd "${ROOT_DIR}"

echo "[harness] root: ${ROOT_DIR}"

if [[ ! -x "${PY_BIN}" ]]; then
  echo "[harness] creating venv at ${VENV_DIR}"
  python3 -m venv "${VENV_DIR}"
fi

echo "[harness] installing python dependencies"
"${PIP_BIN}" install --quiet --upgrade pip
"${PIP_BIN}" install --quiet -r requirements.txt

echo "[harness] compile checks"
"${PY_BIN}" -m py_compile \
  app/main.py \
  app/weather_client.py \
  app/secure_settings.py \
  scripts/security_check.py \
  tests/test_provider_fallback.py \
  tests/test_setup_auth_integration.py \
  tests/integration_smoke.py

echo "[harness] unit tests"
"${PY_BIN}" -m unittest -v tests/test_provider_fallback.py tests/test_setup_auth_integration.py

if [[ "${SKIP_DOCKER}" != "1" ]]; then
  echo "[harness] docker build/start"
  docker compose up -d --build weather-app
fi

echo "[harness] health check (with warm-up retries)"
HEALTH_OK=0
for attempt in 1 2 3 4 5; do
  if ./health-check.sh; then
    HEALTH_OK=1
    break
  fi
  echo "[harness] health check attempt ${attempt} failed; retrying in 2s"
  sleep 2
done
if [[ "${HEALTH_OK}" != "1" ]]; then
  echo "[harness] health check failed after retries"
  exit 1
fi

echo "[harness] integration smoke"
WEATHERAPP_BASE_URL="${BASE_URL}" "${PY_BIN}" tests/integration_smoke.py

echo "[harness] secret leak check"
WEATHERAPP_BASE_URL="${BASE_URL}" "${PY_BIN}" scripts/security_check.py

echo "[harness] ALL CHECKS PASSED"

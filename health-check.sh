#!/bin/bash
# Health check script — verify weather app is running

HOST="${1:-localhost:8888}"

echo "Checking weather app at http://$HOST..."
echo ""

# _check_endpoint <label> <url> <acceptable_codes_grep_pattern> [retries] [delay_seconds]
# Acceptable codes is a grep pattern matched against the HTTP status code.
# Use "200" for infra endpoints; "200\|502" for weather-data endpoints that
# may legitimately 502 when no provider API keys / valid coordinates are set.
_check_endpoint() {
    local label="$1"
    local url="$2"
    local pattern="${3:-200}"
    local retries="${4:-1}"
    local delay="${5:-0}"
    echo -n "${label}: "
    local code="000"

    for ((i=1; i<=retries; i++)); do
        code=$(curl -s -o /dev/null -w "%{http_code}" "${url}")
        if echo "${code}" | grep -qE "${pattern}"; then
            echo "✓ OK (${code})"
            return 0
        fi
        if (( i < retries )) && (( delay > 0 )); then
            sleep "${delay}"
        fi
    done

    echo "✗ FAILED (${code})"
    return 1
}

# Config can fail briefly right after container start; allow warm-up retries.
_check_endpoint "Config endpoint"     "http://$HOST/api/config"       "200"      15 1 || exit 1
_check_endpoint "Bootstrap endpoint"  "http://$HOST/api/bootstrap"    "200"       || exit 1
_check_endpoint "Current conditions"  "http://$HOST/api/current"      "200|502"   || exit 1
_check_endpoint "Active alerts"       "http://$HOST/api/alerts"       "200|502"   || exit 1
_check_endpoint "7-day forecast"      "http://$HOST/api/forecast"     "200|502"   || exit 1
_check_endpoint "Hourly forecast"     "http://$HOST/api/hourly"       "200|502"   || exit 1
_check_endpoint "Swagger UI docs"     "http://$HOST/docs"             "200"       || exit 1
_check_endpoint "OpenAPI spec"        "http://$HOST/openapi.json"     "200"       || exit 1

echo -n "Browser UI: "
if curl -s "http://$HOST" | grep -Eq "Weather Dashboard|Storm Dashboard"; then
    echo "✓ OK"
else
    echo "✗ FAILED"
    exit 1
fi

echo ""
echo "✓ All systems operational!"
echo ""
echo "Web Interface: http://$HOST"
echo "Swagger Docs:  http://$HOST/docs"
echo "OpenAPI Spec:  http://$HOST/openapi.json"


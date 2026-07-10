#!/usr/bin/env bash
# Repeatable load test: runs normal, stress, and failure traffic scenarios
# against the running stack via k6. Uses a local k6 binary if present,
# otherwise runs grafana/k6 in Docker attached to the compose network.
set -euo pipefail

cd "$(dirname "$0")/.."

RESULTS_DIR="docs/benchmark-results"
SCRIPT="scripts/load-test.js"
mkdir -p "$RESULTS_DIR"

if command -v k6 >/dev/null 2>&1; then
  BASE_URL="${BASE_URL:-http://localhost:8080}"
  run_k6() { k6 "$@"; }
else
  echo "k6 not found locally; running via Docker on the compose network" >&2
  NGINX_CID=$(docker compose ps -q nginx)
  if [ -z "$NGINX_CID" ]; then
    echo "nginx isn't running. Start the stack first: docker compose up -d" >&2
    exit 1
  fi
  NETWORK=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' "$NGINX_CID")
  BASE_URL="http://nginx"
  run_k6() { docker run --rm --network "$NETWORK" -v "$(pwd):/work" -w /work grafana/k6 "$@"; }
fi

for SCENARIO in normal stress failure; do
  echo
  echo "=== ${SCENARIO} traffic ==="
  run_k6 run \
    -e SCENARIO="$SCENARIO" \
    -e BASE_URL="$BASE_URL" \
    "$SCRIPT" 2>&1 | tee "$RESULTS_DIR/${SCENARIO}.log"
done

echo
echo "Full k6 output saved to $RESULTS_DIR/{normal,stress,failure}.log"
echo "See docs/benchmark-report.md for the human-readable results table."

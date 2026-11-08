#!/usr/bin/env bash
# Checks the service API contract on the built image, including FAULT_INJECT=1. Writes results/service_api.txt.
# Run as   ./scripts/with_s3.sh scripts/check_service_api.sh
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE=${IMAGE:-parser-service:1}
PORT=${PORT:-18001}
OUT=results/service_api.txt
mkdir -p results
trap 'docker rm -f parser-api-test parser-fault-test >/dev/null 2>&1 || true' EXIT

start() {  # name, FAULT_INJECT value
  docker rm -f "$1" >/dev/null 2>&1 || true
  docker run -d --name "$1" --network host -e MODEL_URI=s3://models/v2 -e MODEL_VERSION=v2 -e S3_ENDPOINT \
    -e MAX_NEW_TOKENS=80 -e FAULT_INJECT="$2" -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_DEFAULT_REGION \
    "$IMAGE" uvicorn app:app --host 0.0.0.0 --port "$PORT" >/dev/null
  for _ in $(seq 1 120); do [ "$(curl -s -o /dev/null -w '%{http_code}' localhost:$PORT/readyz)" = 200 ] && return; sleep 1; done
  echo "service did not become ready"; exit 1
}
show() {  # curl with status line and the two headers
  curl -s -i -X POST localhost:$PORT/parse -H 'Content-Type: application/json' -d "$1" | grep -iE '^(HTTP|x-model-version|x-served-by)|^\{|^$' | tr -d '\r' | grep -v '^$'
}
{
echo "# $(date -u +%FT%TZ)  image=$IMAGE"
echo "== FAULT_INJECT=0"
start parser-api-test 0
echo "-- GET /healthz: $(curl -s -w ' [HTTP %{http_code}]' localhost:$PORT/healthz)"
echo "-- GET /readyz:  $(curl -s -w ' [HTTP %{http_code}]' localhost:$PORT/readyz)"
echo "-- POST /parse {\"text\": \"set an alarm for seven thirty am tomorrow\"}"; show '{"text": "set an alarm for seven thirty am tomorrow"}'
echo "-- POST /parse {\"text\": \"what is the weather in london\"}"; show '{"text": "what is the weather in london"}'
echo "-- POST /parse with an empty text (expect HTTP 422)"; show '{"text": ""}'
docker rm -f parser-api-test >/dev/null
echo "== FAULT_INJECT=1"
start parser-fault-test 1
echo "-- GET /healthz: $(curl -s -w ' [HTTP %{http_code}]' localhost:$PORT/healthz)"
echo "-- POST /parse (the model output is replaced by the text: not json)"; show '{"text": "set an alarm for seven thirty am tomorrow"}'
} 2>&1 | tee "$OUT"

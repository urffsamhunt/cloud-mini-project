#!/usr/bin/env bash
# Task 3 limits test: run the service image with 1 CPU and 1 GiB, send 50 requests one after another,
# and report peak memory and whether the container was OOM-killed. Writes results/service_limits.txt.
# Needs S3 access to the models bucket: run it as   ./scripts/with_s3.sh scripts/check_service_limits.sh
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE=${IMAGE:-parser-service:1}
MODEL_URI=${MODEL_URI:-s3://models/v1}
NAME=parser-limits-test
PORT=${PORT:-18000}   # host networking is used, so pick a port that is free on the host
OUT=results/service_limits.txt
mkdir -p results
docker rm -f "$NAME" >/dev/null 2>&1 || true
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT

docker run -d --name "$NAME" --cpus=1 --memory=1g --memory-swap=1g --network host \
  -e MODEL_URI="$MODEL_URI" -e MODEL_VERSION="${MODEL_VERSION:-v1}" -e S3_ENDPOINT -e MAX_NEW_TOKENS=80 \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_DEFAULT_REGION "$IMAGE" uvicorn app:app --host 0.0.0.0 --port "$PORT" >/dev/null

{
echo "# $(date -u +%FT%TZ)  image=$IMAGE  model=$MODEL_URI  limits: cpus=1 memory=1GiB (no swap)"
docker image inspect "$IMAGE" --format 'image size: {{.Size}} bytes'
for _ in $(seq 1 60); do curl -s -m 2 localhost:$PORT/healthz >/dev/null && break; sleep 1; done
echo "healthz: $(curl -s -o /dev/null -w '%{http_code}' localhost:$PORT/healthz)"
echo "readyz while loading: $(curl -s -o /dev/null -w '%{http_code}' localhost:$PORT/readyz)"
T0=$(date +%s)
until [ "$(curl -s -o /dev/null -w '%{http_code}' localhost:$PORT/readyz)" = 200 ]; do
  sleep 1; [ $(( $(date +%s) - T0 )) -lt 240 ] || { echo "model did not become ready"; docker logs "$NAME" | tail -20; exit 1; }
done
echo "readyz after load: 200 (took about $(( $(date +%s) - T0 )) s after the check above)"
docker logs "$NAME" 2>&1 | grep -E 'downloaded|checksums|ready after'
PORT=$PORT python3 -I - <<'PY'
import json, os, time, urllib.request, collections
rows = [json.loads(l) for l in open("data/validation.jsonl")][:50]
codes, lat = collections.Counter(), []
for i, r in enumerate(rows):
    req = urllib.request.Request(f"http://localhost:{os.environ['PORT']}/parse", json.dumps({"text": r["text"]}).encode(), {"Content-Type": "application/json"})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            codes[resp.status] += 1
            if i == 0: print("first reply:", resp.read().decode(), "| X-Model-Version:", resp.headers["X-Model-Version"], "| X-Served-By:", resp.headers["X-Served-By"])
    except urllib.error.HTTPError as e:
        codes[e.code] += 1
    lat.append(time.time() - t)
lat.sort()
print(f"requests: {len(rows)}  status codes: {dict(codes)}  p50 {lat[len(lat)//2]*1000:.0f} ms  p95 {lat[int(len(lat)*.95)]*1000:.0f} ms  max {lat[-1]*1000:.0f} ms")
PY
echo "peak memory (cgroup memory.peak): $(docker exec "$NAME" cat /sys/fs/cgroup/memory.peak) bytes"
echo "docker stats: $(docker stats --no-stream --format '{{.MemUsage}}  cpu {{.CPUPerc}}' "$NAME")"
echo "OOMKilled: $(docker inspect "$NAME" --format '{{.State.OOMKilled}}')  restarts: $(docker inspect "$NAME" --format '{{.RestartCount}}')"
} 2>&1 | tee "$OUT"

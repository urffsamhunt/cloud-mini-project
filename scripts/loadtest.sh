#!/usr/bin/env bash
# Task 7 load test with the handout's settings, plus a sampler for `kubectl top pods`
# and the replica count every 10 s. Writes results/${OUT}_* (default loadtest_*).
# Needs the stack up (make up) and: pip install -r requirements-loadtest.txt (venv .venv-load).
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d .venv-load ] || python3 -m venv .venv-load
.venv-load/bin/pip install -q -r requirements-loadtest.txt
OUT=${OUT:-loadtest}   # file prefix in results/, e.g. OUT=loadtest_v2
export LOADTEST_HEADERS_OUT=results/${OUT}_headers.json
mkdir -p results
SAMPLES=results/${OUT}_top.txt
: > "$SAMPLES"
( while true; do
    echo "--- $(date +%T) replicas(ready)=$(kubectl -n app get deploy parser -o jsonpath='{.status.readyReplicas}')/$(kubectl -n app get deploy parser -o jsonpath='{.spec.replicas}')" >> "$SAMPLES"
    kubectl top pods -n app --no-headers >> "$SAMPLES" 2>&1 || true
    sleep 10
  done ) &
SAMPLER=$!
trap 'kill $SAMPLER 2>/dev/null || true' EXIT
.venv-load/bin/locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 --run-time 2m \
  --host http://localhost:8080 --csv results/$OUT 2>&1 | tee results/${OUT}_console.txt

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
# The handout's load-balancing condition: exactly two Ready replicas while the test runs. An idle HPA would scale
# the deployment back to 1 before the load starts, so it is removed for the run and restored (kubectl apply) at the end.
kubectl -n app delete hpa parser --ignore-not-found >/dev/null
kubectl -n app scale deploy/parser --replicas=2 >/dev/null
kubectl -n app rollout status deploy/parser --timeout=300s >/dev/null
until [ "$(kubectl -n app get pods -l app=parser --no-headers | wc -l)" = "2" ] && \
      [ "$(kubectl -n app get pods -l app=parser --no-headers | grep -c ' 1/1 .*Running')" = "2" ]; do sleep 1; done
mkdir -p results
SAMPLES=results/${OUT}_top.txt
: > "$SAMPLES"
( while true; do
    echo "--- $(date +%T) replicas(ready)=$(kubectl -n app get deploy parser -o jsonpath='{.status.readyReplicas}')/$(kubectl -n app get deploy parser -o jsonpath='{.spec.replicas}')" >> "$SAMPLES"
    kubectl top pods -n app --no-headers >> "$SAMPLES" 2>&1 || true
    sleep 10
  done ) &
SAMPLER=$!
trap 'kill $SAMPLER 2>/dev/null || true; kubectl apply -f k8s/app.yaml >/dev/null' EXIT
.venv-load/bin/locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 --run-time 2m \
  --host http://localhost:8080 --csv results/$OUT 2>&1 | tee results/${OUT}_console.txt

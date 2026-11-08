#!/usr/bin/env bash
# Task 4 HPA evidence: 1 -> 2 replicas under load, then back to 1 after the load stops.
# Starts from 1 replica, sends Locust load for 4 minutes, then waits (up to 10 min) for the scale-down.
# The HPA default scale-down stabilisation window is 5 minutes, so the whole test takes about 10 minutes.
set -uo pipefail
cd "$(dirname "$0")/.."
OUT=results/task4_scaling.txt
[ -d .venv-load ] || python3 -m venv .venv-load
.venv-load/bin/pip install -q -r requirements-loadtest.txt
kubectl apply -f k8s/app.yaml >/dev/null
kubectl -n app scale deploy/parser --replicas=1 >/dev/null
kubectl -n app rollout status deploy/parser --timeout=300s >/dev/null
sample() { echo "$(date +%T) hpa: $(kubectl -n app get hpa parser -o jsonpath='cpu={.status.currentMetrics[0].resource.current.averageUtilization}% current={.status.currentReplicas} desired={.status.desiredReplicas}') ready=$(kubectl -n app get deploy parser -o jsonpath='{.status.readyReplicas}') $(kubectl top pods -n app --no-headers 2>/dev/null | awk '{printf "%s=%s ",$1,$2}')"; }
{
  echo "== HPA: start with 1 replica, 4 users for 4 minutes, then idle =="
  sample
  LOADTEST_HEADERS_OUT=results/task4_scaling_headers.json .venv-load/bin/locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 \
    --run-time 240s --host http://localhost:8080 --csv results/task4_scaling > results/task4_scaling_console.txt 2>&1 &
  LOAD=$!
  while kill -0 $LOAD 2>/dev/null; do sample; sleep 10; done
  echo "--- load stopped; waiting for the scale-down ---"
  for i in $(seq 1 70); do
    sample
    [ "$(kubectl -n app get deploy parser -o jsonpath='{.spec.replicas}')" = "1" ] && [ "$(kubectl -n app get pods -l app=parser --no-headers | wc -l)" = "1" ] && { echo "back to 1 replica"; break; }
    sleep 10
  done
  kubectl -n app describe hpa parser | sed -n '/Events:/,$p'
} | tee $OUT

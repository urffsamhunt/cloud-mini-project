#!/usr/bin/env bash
# Task 4 evidence: load balancing, pod recovery, rolling update + rollback, cold start x3.
# Needs the cluster up and k8s/app.yaml applied. Writes results/task4_*.txt.
set -uo pipefail
cd "$(dirname "$0")/.."
URL=${URL:-http://localhost:8080}
NS=app
mkdir -p results
now() { date +%s.%N; }
req() { curl -s -o /dev/null -w '%{http_code} %header{x-served-by} %header{x-model-version}\n' \
        --max-time 10 -X POST "$URL/parse" -H 'content-type: application/json' \
        -d '{"text":"what is the weather in paris tomorrow"}'; }
wait_ready() { kubectl -n $NS rollout status deploy/parser --timeout=300s >/dev/null; }
# settle: exactly 2 pods, all Ready, none terminating (old pods drain for the preStop delay)
settle() { until [ "$(kubectl -n $NS get pods -l app=parser --no-headers | wc -l)" = "2" ] && \
  [ "$(kubectl -n $NS get pods -l app=parser --no-headers | grep -c ' 1/1 .*Running')" = "2" ]; do sleep 1; done; sleep 5; }

# ---- 1. load balancing: 100 requests, share per pod
{
  echo "== load balancing: 200 sequential requests via Ingress =="
  wait_ready; settle
  for i in $(seq 200); do req; done | tee /tmp/lb.$$ >/dev/null
  echo "status codes:"; awk '{print $1}' /tmp/lb.$$ | sort | uniq -c
  echo "requests per pod (X-Served-By):"; awk '{print $2}' /tmp/lb.$$ | sort | uniq -c
  rm -f /tmp/lb.$$
} | tee results/task4_loadbalancing.txt

# ---- 2. pod deletion recovery with a steady request stream
{
  echo "== pod deletion: delete one pod while sending 1 request every 0.2 s =="
  victim=$(kubectl -n $NS get pods -l app=parser -o jsonpath='{.items[0].metadata.name}')
  ( for i in $(seq 150); do echo "$(now) $(req)"; sleep 0.2; done ) > /tmp/rec.$$ &
  sleep 5
  t0=$(now); echo "deleting $victim at t0"
  kubectl -n $NS delete pod "$victim" --wait=false >/dev/null
  kubectl -n $NS wait --for=delete pod/"$victim" --timeout=60s >/dev/null 2>&1
  until [ "$(kubectl -n $NS get pods -l app=parser --no-headers 2>/dev/null | grep -c ' 1/1 .*Running')" = "2" ]; do sleep 0.5; done
  t1=$(now)
  printf 'back to 2 ready replicas after %.1f s\n' "$(echo "$t1 - $t0" | bc -l)"
  wait
  echo "status codes during the test:"; awk '{print $2}' /tmp/rec.$$ | sort | uniq -c
  rm -f /tmp/rec.$$
} | tee results/task4_recovery.txt

# ---- 3. rolling update v1 -> v2, then rollback
{
  echo "== rolling update v1 -> v2 with request stream =="
  ( for i in $(seq 500); do echo "$(req)"; sleep 0.2; done ) > /tmp/roll.$$ &
  sleep 3
  kubectl -n $NS set env deploy/parser MODEL_VERSION=v2 MODEL_URI=s3://models/v2/ >/dev/null
  kubectl -n $NS annotate deploy/parser kubernetes.io/change-cause="model v1 -> v2" --overwrite >/dev/null
  wait_ready
  echo "rollout to v2 complete"; sleep 10; kubectl -n $NS rollout history deploy/parser
  echo "--- rollback ---"
  kubectl -n $NS rollout undo deploy/parser >/dev/null
  kubectl -n $NS annotate deploy/parser kubernetes.io/change-cause="rollback to v1" --overwrite >/dev/null
  wait_ready
  echo "rollback complete"
  wait
  echo "status code / model version counts during update+rollback:"
  awk '{print $1, $3}' /tmp/roll.$$ | sort | uniq -c
  rm -f /tmp/roll.$$
  echo "final version: $(curl -s -D- -o /dev/null -X POST $URL/parse -H 'content-type: application/json' -d '{"text":"hi"}' | grep -i x-model-version)"
} | tee results/task4_rollout.txt

# ---- 4. cold start x3 (scale 0 -> 1: pod create until Ready)
{
  echo "== cold start: pod scheduled -> Ready, 3 runs (HPA paused by scaling the Deployment directly) =="
  kubectl -n $NS delete hpa parser >/dev/null
  times=()
  for run in 1 2 3; do
    kubectl -n $NS scale deploy/parser --replicas=0 >/dev/null
    kubectl -n $NS wait --for=delete pod -l app=parser --timeout=120s >/dev/null 2>&1
    t0=$(now)
    kubectl -n $NS scale deploy/parser --replicas=1 >/dev/null
    until [ "$(kubectl -n $NS get deploy parser -o jsonpath='{.status.readyReplicas}')" = "1" ]; do sleep 0.25; done
    t1=$(now)
    d=$(echo "$t1 - $t0" | bc -l); times+=("$d")
    printf 'run %d: %.1f s\n' "$run" "$d"
  done
  printf '%s\n' "${times[@]}" | sort -n | sed -n 2p | xargs printf 'median: %.1f s\n'
  kubectl -n $NS scale deploy/parser --replicas=2 >/dev/null
  kubectl apply -f k8s/app.yaml >/dev/null    # restores the HPA
  wait_ready; settle
} | tee results/task4_coldstart.txt

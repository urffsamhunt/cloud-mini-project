#!/usr/bin/env bash
# Task 4 evidence: endpoints while loading, recovery, rolling update + rollback, cold start x3.
# Load for the recovery and rollout tests comes from Locust (tools/locustfile.py, 4 users, longer --run-time).
# Needs the stack up (make up). Writes results/task4_*. The HPA is removed while the tests run and
# restored (kubectl apply of k8s/app.yaml) at the end. Load balancing and scaling: make loadtest, task4_scaling.sh.
set -uo pipefail
cd "$(dirname "$0")/.."
URL=${URL:-http://localhost:8080}
NS=app
mkdir -p results
[ -d .venv-load ] || python3 -m venv .venv-load
.venv-load/bin/pip install -q -r requirements-loadtest.txt
LOCUST=.venv-load/bin/locust

now() { date +%s.%N; }
ready_pods() { kubectl -n $NS get pods -l app=parser --no-headers 2>/dev/null | grep -c ' 1/1 .*Running'; }
all_pods() { kubectl -n $NS get pods -l app=parser --no-headers 2>/dev/null | wc -l; }
wait_ready() { kubectl -n $NS rollout status deploy/parser --timeout=300s >/dev/null; }
# settle: exactly 2 pods, all Ready, none terminating (old pods drain during the preStop delay)
settle() { until [ "$(all_pods)" = "2" ] && [ "$(ready_pods)" = "2" ]; do sleep 1; done; sleep 5; }
version_header() { curl -s -D- -o /dev/null -X POST $URL/parse -H 'content-type: application/json' -d '{"text":"hi"}' | tr -d '\r' | grep -i x-model-version; }
# start_load NAME SECONDS  -> background Locust, pid in $LOAD_PID
start_load() {
  LOADTEST_HEADERS_OUT=results/$1_headers.json $LOCUST -f tools/locustfile.py --headless --users 4 --spawn-rate 4 \
    --run-time "$2" --host $URL --csv results/$1 > results/$1_console.txt 2>&1 &
  LOAD_PID=$!
}
# summarise NAME -> counts from the Locust csv files
summarise() {
  python3 - "$1" <<'PY'
import csv, json, sys
n = sys.argv[1]
r = [x for x in csv.DictReader(open(f"results/{n}_stats.csv")) if x["Name"] == "Aggregated"][0]
req, fail = int(r["Request Count"]), int(r["Failure Count"])
print(f"requests {req}, failures {fail} ({100 * fail / req:.2f} %), p50 {r['50%']} ms, p95 {r['95%']} ms, {float(r['Requests/s']):.2f} req/s")
for x in csv.DictReader(open(f"results/{n}_failures.csv")):
    print(f"  failure type: {x['Error']}  x{x['Occurrences']}")
print("served by header:", json.load(open(f"results/{n}_headers.json")))
PY
}

# SECTIONS="rollout" runs only that part. ROLLOUT_NAME / LOADTEST_TEXTS let the rolling update run with another
# command list (see task4_rollout_clean.sh).
want() { [[ " ${SECTIONS:-endpoints recovery rollout coldstart} " == *" $1 "* ]]; }
ROLLOUT_NAME=${ROLLOUT_NAME:-task4_rollout}
export LOADTEST_TEXTS=${LOADTEST_TEXTS:-data/validation.jsonl}

kubectl -n $NS delete hpa parser --ignore-not-found >/dev/null
kubectl -n $NS set env deploy/parser MODEL_VERSION=v2 MODEL_URI=s3://models/v2/ >/dev/null
kubectl -n $NS scale deploy/parser --replicas=2 >/dev/null
wait_ready; settle

# ---- 1. no ready endpoints while the model is loading
if want endpoints; then
{
  echo "== Service endpoints while the model is loading (scale to 0, then to 1; poll every second) =="
  kubectl -n $NS scale deploy/parser --replicas=0 >/dev/null
  until [ "$(all_pods)" = "0" ]; do sleep 1; done
  kubectl -n $NS scale deploy/parser --replicas=1 >/dev/null
  t0=$(now)
  for i in $(seq 1 14); do
    pod=$(kubectl -n $NS get pods -l app=parser --no-headers | awk '{print $1" "$2" "$3}')
    ep=$(kubectl -n $NS get endpoints parser -o jsonpath='ready={.subsets[*].addresses[*].ip} notReady={.subsets[*].notReadyAddresses[*].ip}' 2>/dev/null)
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 $URL/readyz)
    printf 't=%4.1fs  pod: %-32s  endpoints: %-40s  GET /readyz via Ingress: %s\n' "$(echo "$(now) - $t0" | bc -l)" "$pod" "$ep" "$code"
    sleep 1
  done
  kubectl -n $NS scale deploy/parser --replicas=2 >/dev/null
  wait_ready; settle
} | tee results/task4_endpoints_loading.txt
fi

# ---- 2. recovery: delete one pod under Locust load
if want recovery; then
{
  echo "== pod deletion under load (Locust, 4 users, 90 s; one pod deleted at 20 s) =="
  start_load task4_recovery 90s
  sleep 20
  victim=$(kubectl -n $NS get pods -l app=parser -o jsonpath='{.items[0].metadata.name}')
  echo "deleting $victim; ready replicas before: $(ready_pods)"
  t0=$(now)
  kubectl -n $NS delete pod "$victim" --wait=false >/dev/null
  kubectl -n $NS wait --for=delete pod/"$victim" --timeout=60s >/dev/null 2>&1
  until [ "$(ready_pods)" = "2" ] && [ "$(all_pods)" = "2" ]; do sleep 0.5; done
  printf 'two ready replicas again after %.1f s (deployment readyReplicas=%s)\n' "$(echo "$(now) - $t0" | bc -l)" \
    "$(kubectl -n $NS get deploy parser -o jsonpath='{.status.readyReplicas}')"
  wait $LOAD_PID
  summarise task4_recovery
} | tee results/task4_recovery.txt
fi

# ---- 3. rolling update v1 -> v2 and rollback under Locust load
if want rollout; then
{
  echo "== rolling update v1 -> v2, then rollout undo, under Locust load (4 users, 4 min) =="
  # k8s/app.yaml serves v2 by default; this test starts from v1 as the first release, as in the handout.
  kubectl -n $NS set env deploy/parser MODEL_VERSION=v1 MODEL_URI=s3://models/v1/ >/dev/null
  kubectl -n $NS annotate deploy/parser kubernetes.io/change-cause="baseline: model v1" --overwrite >/dev/null
  wait_ready; settle
  echo "start state: $(version_header)"
  start_load $ROLLOUT_NAME 240s
  sleep 30
  echo "$(date +%T) set MODEL_VERSION=v2 MODEL_URI=s3://models/v2/"
  kubectl -n $NS set env deploy/parser MODEL_VERSION=v2 MODEL_URI=s3://models/v2/ >/dev/null
  kubectl -n $NS annotate deploy/parser kubernetes.io/change-cause="model v1 -> v2" --overwrite >/dev/null
  wait_ready; echo "$(date +%T) rollout to v2 complete; serving: $(version_header)"
  sleep 30
  kubectl -n $NS rollout history deploy/parser
  echo "$(date +%T) kubectl rollout undo"
  kubectl -n $NS rollout undo deploy/parser 2>/dev/null
  kubectl -n $NS annotate deploy/parser kubernetes.io/change-cause="rollback to v1" --overwrite >/dev/null
  wait_ready; settle
  echo "$(date +%T) rollback complete; after rollback: $(version_header)"
  wait $LOAD_PID
  summarise $ROLLOUT_NAME
  echo "--- promote v2 again (the manifest default) ---"
  kubectl -n $NS set env deploy/parser MODEL_VERSION=v2 MODEL_URI=s3://models/v2/ >/dev/null
  kubectl -n $NS annotate deploy/parser kubernetes.io/change-cause="promote model v2 (manifest default)" --overwrite >/dev/null
  wait_ready; settle
  echo "final: $(version_header)"
} | tee results/$ROLLOUT_NAME.txt
fi

# ---- 4. cold start x3: delete ALL pods; time from Pod creation to Ready (from the Kubernetes API)
if want coldstart; then
{
  echo "== cold start: delete all pods, 3 runs; creation -> Ready from the API (per run: the slower of the 2 pods) =="
  : > results/task4_coldstart_logs.txt
  runs=()
  for run in 1 2 3; do
    kubectl -n $NS delete pods -l app=parser --wait=true >/dev/null
    until [ "$(all_pods)" = "2" ] && [ "$(ready_pods)" = "2" ]; do sleep 0.5; done
    echo "--- run $run ---" | tee -a results/task4_coldstart_logs.txt >/dev/null
    worst=0
    for p in $(kubectl -n $NS get pods -l app=parser -o jsonpath='{.items[*].metadata.name}'); do
      t=$(kubectl -n $NS get pod $p -o json | python3 -c '
import json, sys
from datetime import datetime
d = json.load(sys.stdin)
f = lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").timestamp()
ready = [c for c in d["status"]["conditions"] if c["type"] == "Ready"][0]["lastTransitionTime"]
print(f(ready) - f(d["metadata"]["creationTimestamp"]))')
      echo "run $run pod $p: Ready ${t} s after creation (1 s resolution)"
      worst=$(python3 -c "print(max($worst, $t))")
      { echo "[$p]"; kubectl -n $NS logs $p | grep -E "downloaded|checksums verified|ready after"; } >> results/task4_coldstart_logs.txt
    done
    runs+=("$worst"); echo "run $run: $worst s"
  done
  python3 -c "import statistics, sys; v=[float(x) for x in sys.argv[1:]]; print('runs:', v, 'median:', statistics.median(v), 's')" "${runs[@]}"
} | tee results/task4_coldstart.txt
fi

want coldstart && head -12 results/task4_coldstart_logs.txt

kubectl apply -f k8s/app.yaml >/dev/null   # restores the HPA
wait_ready

# Task 7: performance, cost and review

All numbers are **measured** unless a line says "assumption". Command (via `make loadtest`, `scripts/loadtest.sh`):
`locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 --run-time 2m --host http://localhost:8080 --csv results/<OUT>`
Host: one laptop, k3d cluster with one node; Locust, Traefik, both replicas and SeaweedFS share the same CPU.

## Official run (model v2, exactly two Ready replicas): `results/loadtest_*`

The HPA is removed for the run and restored afterwards, so that exactly two replicas are Ready throughout (an idle HPA scales an unloaded deployment back to 1 before the load starts).

| Measurement | Value |
|---|---|
| Requests / failures | 500 / 0 |
| **Error rate** | **0 %** |
| **p50 / p95 latency** | **940 ms / 1500 ms** |
| **Throughput** | **4.21 req/s** |
| Requests per replica (`X-Served-By`) | 252 and 252 (50 % each); all 504 successes were served by v2 |
| `kubectl top pods` (sampled every 10 s) | CPU 986-993 m per pod at steady state (limit 1000 m, request 500 m); memory 383-566 MiB per pod (limit 1 GiB) |
| Cold start (Task 4, `results/task4_coldstart.txt`) | 7.0 s, 7.0 s, 6.0 s; median 7.0 s |

Files: `results/loadtest_stats.csv`, `_stats_history.csv`, `_failures.csv`, `_exceptions.csv`, `_headers.json`, `_console.txt`, `_top.txt`.
The CSV request count (500) is what Locust wrote at shutdown; the console shows a few more requests in flight (504).

## Comparison run with model v1: `results/loadtest_v1_*`

Started with 1 replica; the HPA added the second after about 55 s.

| | v1 (`loadtest_v1_*`) | v2 (official) |
|---|---|---|
| Requests / failures | 432 / 4 | 500 / 0 |
| Error rate | 0.93 % | 0 % |
| p50 / p95 | 1300 / 1600 ms | 940 / 1500 ms |
| Throughput | 3.63 req/s | 4.21 req/s |

The 4 failures of the v1 run are all HTTP 500 `invalid_model_output`, the schema check catching broken JSON. They are one validation command (V049, "what is the address for the event scheduled on the first of january alexa") that model v1 answers with truncated JSON (`"date": "the first of january apera"}` with keys missing). The load test cycles the 100 validation commands, so it comes back once per cycle (4 cycles = 4 failures). The expected error rate of v1 is 1 in 100, which is why v2 (100 % validity on the validation set) is the deployed model. The same effect shows up in the rolling-update test (`results/task4_rollout.txt`): 10 failures in 1,180 requests (0.85 %), all HTTP 500, while v1 was serving; without V049 in the command list (`results/task4_rollout_without_V049.txt`) the same test had 0 failures in 707 requests.

## Cost per 1,000 requests (rates from `data/rate_card.json`: 3.50 INR per vCPU-hour, 0.45 INR per GiB-hour)

1. One replica is billed for its limits: CPU limit 1 vCPU, memory limit 1 GiB.
   Hourly cost of one replica = 1 × 3.50 + 1 × 0.45 = **3.95 INR**.
2. Replicas running during the official run: 2 (measured, `loadtest_top.txt`: `replicas(ready)=2/2`).
   Hourly cost of all replicas = 2 × 3.95 = **7.90 INR**.
3. Requests served per hour = successful requests in the 120 s run × (3600 / 120) = 500 × 30 = **15,000** per hour.
4. Cost per 1,000 requests = 7.90 / 15,000 × 1000 = **0.527 INR**.

Sensitivity (same formula): with one replica the hourly cost halves (3.95 INR), but one replica would not serve the same throughput. For the v1 run (428 successful requests, 12,840 per hour, two replicas assumed) the result is 7.90 / 12,840 × 1000 = 0.615 INR. An idle pair of replicas still costs 7.90 INR per hour, because billing is by limits, not use. This is an estimate; nothing is charged on the laptop.

## SLO and error budget

- **SLO:** 99 % of `POST /parse` requests return HTTP 200 (a valid four-key JSON object) within 30 s (the Locust failure rule).
- **Window:** one load-test run (120 s, 4 users).
- **Error budget** = 1 % of the requests in the window.

| | Requests | Budget (requests) | Failures | Budget used | SLO met? |
|---|---|---|---|---|---|
| Official run (v2) | 500 | 5.00, so 5 requests | 0 | **0 %** | yes (100 %) |
| v1 run (comparison) | 432 | 4.32, so 4 whole requests | 4 | 4 / 4.32 = **92.6 %** | yes (99.07 %), almost no budget left |

Latency target for the marking criterion (not my SLO): p95 at most 5,000 ms. Measured 1,500 ms.

## Review table

| Component or concern | Evidence (a measured number) | Limitation found | Improvement proposed |
|---|---|---|---|
| Data and storage | Teacher output 3,000 records, 2,903 kept (97 rejected: 40 slot not in command, 50 duplicates, 4 invalid JSON, 2 bad intent, 1 wrong keys). SeaweedFS holds 2 model archives of 285 MB each on a 4 GiB volume. | One SeaweedFS pod on one local volume: no replication, no backup. The largest rejection cause is the teacher inventing slot values that are not in the command (40 of 97). | Replicate or back up the volume (the raw shards are also committed in `data/teacher/`); a stricter prompt or a second labelling pass for slots. |
| Model quality | Validation (100 commands): v1 validity 99 %, full frame 49 %; v2 validity 100 %, full frame 51 %; teacher full frame 54 %; untrained Pythia 0 %. Final training loss 0.034 (v1), 0.024 (v2). | The validation set has 100 commands (one command = 1 point), so v1 and v2 differ within noise; the loss near zero hints at overfitting; the student copied the teacher's wrong answer on 22 of the teacher's 46 errors (v2). | More teacher data and a held-out loss; constrained decoding or a JSON grammar so that broken output cannot occur. |
| Latency and throughput | p50 940 ms, p95 1,500 ms, 4.21 req/s with 4 users and 2 replicas (limit p95 5,000 ms). One request alone: p50 430 ms (Task 3, 1 CPU). | Latency is CPU-bound: 4 users on 2 CPUs queue up (p50 about twice the unloaded time). A closed-loop test is not a real arrival pattern. | Cap `MAX_NEW_TOKENS` closer to the real answer length (not measured; default 80), batch concurrent requests, int8 quantisation or ONNX Runtime. |
| Resource utilisation | CPU 986-993 m of the 1,000 m limit (about 99 % of the limit, about 198 % of the 500 m request); memory 383-566 MiB of 1 GiB (peak 55 % of the limit). | The CPU request (500 m) is half of the real use, so the scheduler under-reserves, and the HPA at 70 % of the request fires as soon as one user is active. Memory grows during the test (383 to 566 MiB on one pod). | CPU request about 900 m, memory request about 640 Mi; watch the memory growth for a leak with a longer run. |
| Reliability and recovery | One pod deleted under load: two ready pods again after 10.4 s, 0 of 334 requests failed. Rolling update v1 to v2 and rollback: 0 of 707 requests failed (V049 excluded); with V049, 10 of 1,180 (0.85 %), all model errors of v1. HPA: scale-up decision about 10 s after the load started, scale-down 5 min after it ended. Cold start median 7.0 s. | One node: no protection against losing the machine. SeaweedFS is a single point of failure: a new pod cannot download its model while it is down. | A multi-node cluster; cache the model on a volume or retry the download in an init container; replicate storage. |
| Security and cost | gitleaks: 0 findings in the git history and in CI. Credentials only in Kubernetes Secrets; container runs as uid 10001. Cost 0.527 INR per 1,000 requests (7.90 INR per hour for 2 replicas). | One shared S3 credential with full access is copied to three namespaces; Secrets are only base64 in etcd; `/parse` has no authentication and the Ingress is plain HTTP on port 8080. Billing by limits means idle replicas cost 7.90 INR per hour. | Read-only credentials for the service, TLS and an API key on the Ingress, encrypted Secrets; scale to 1 replica when idle (halves the idle cost to 3.95 INR per hour). |

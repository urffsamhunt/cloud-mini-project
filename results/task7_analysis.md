# Task 7: performance, cost and review

All numbers are **measured** unless a line says "assumption". Command (via `make loadtest`, `scripts/loadtest.sh`):
`locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 --run-time 2m --host http://localhost:8080 --csv results/<OUT>`
Host: one laptop, k3d cluster with one node; Locust, Traefik, both replicas and SeaweedFS share the same CPU.

Two runs are kept because the model decides the error rate:

| | Run A: `loadtest_*` (model v1, the deployed default) | Run B: `loadtest_v2_*` (model v2) |
|---|---|---|
| Replicas | 1 at start; the HPA added the 2nd at about 55 s (ready at about 65 s) | 2 from the start |
| Requests / failures | 432 / 4 | 548 / 0 |
| **Error rate** | **0.93 %** | **0 %** |
| **p50 / p95 latency** | **1300 ms / 1600 ms** | **800 ms / 1400 ms** |
| **Throughput** | **3.63 req/s** | **4.60 req/s** |
| Requests per replica (header `X-Served-By`) | 299 and 133 (the first replica worked alone at the start) | 276 and 275 |
| `kubectl top pods`, CPU | 990-993 m on the first pod, 918-981 m on the second | 985-990 m on both |
| `kubectl top pods`, memory | 382-454 MiB | 394-401 MiB |
| Cold start (Task 4, `results/task4_coldstart.txt`) | median 7.2 s (7.2, 7.1, 22.1) | same |

Files: `results/loadtest_stats.csv`, `_stats_history.csv`, `_failures.csv`, `_exceptions.csv`, `_headers.json`, `_console.txt`, `_top.txt` (and the same with `loadtest_v2`).
The CSV request counts (432, 548) are the files Locust wrote at shutdown; the console shows a few more in flight (436, 551).

Why the 4 failures in run A: all four are HTTP 500 `invalid_model_output`, the service's schema check catching broken JSON. They are one validation command (V049, "what is the address for the event scheduled on the first of january alexa") that model v1 answers with truncated JSON (`"date": "the first of january apera"}` with keys missing). The load test cycles the 100 validation commands, so that command comes back once per cycle (4 cycles = 4 failures). The expected error rate for v1 is 1 in 100 = 1 %; 0.93 % is that, cut off in the middle of a cycle. Model v2 returns valid JSON for all 100 commands, hence 0 failures. **Risk:** a different run length could end at exactly 1.0 % or slightly above for v1.

## Cost per 1,000 requests (rates from `data/rate_card.json`: 3.50 INR per vCPU-hour, 0.45 INR per GiB-hour)

1. One replica is billed for its limits: CPU limit 1 vCPU, memory limit 1 GiB.
   Hourly cost of one replica = 1 × 3.50 + 1 × 0.45 = **3.95 INR**.
2. Replicas running: 2 (assumption: the cost is calculated for the 2 replicas that are running once the HPA has scaled up; run A had only 1 replica for its first minute).
   Hourly cost of all replicas = 2 × 3.95 = **7.90 INR**.
3. Requests served per hour = successful requests in the 120 s run × (3600 / 120):
   - Run A: (432 − 4) × 30 = **12,840** per hour.
   - Run B: 548 × 30 = **16,440** per hour.
4. Cost per 1,000 requests = 7.90 / requests per hour × 1000:
   - Run A (v1): 7.90 / 12,840 × 1000 = **0.615 INR**.
   - Run B (v2): 7.90 / 16,440 × 1000 = **0.481 INR**.

Sensitivity (computed, same formula): with one replica the same traffic would cost half (0.308 INR for run A, 0.240 INR for run B) but one replica cannot serve the throughput of two. An idle pair of replicas still costs 7.90 INR per hour, because billing is by limits, not use. This is an estimate; nothing is charged on the laptop.

## SLO and error budget

- **SLO:** 99 % of `POST /parse` requests return HTTP 200 (a valid four-key JSON object) within 30 s (the Locust failure rule).
- **Window:** one load-test run (120 s, 4 users).
- **Error budget** = 1 % of the requests in the window.

| | Requests | Budget (requests) | Failures | Budget used | SLO met? |
|---|---|---|---|---|---|
| Run A (v1) | 432 | 4.32, so 4 whole requests | 4 | 4 / 4.32 = **92.6 %** | yes (99.07 % succeeded), but almost no budget left |
| Run B (v2) | 548 | 5.48, so 5 whole requests | 0 | **0 %** | yes (100 %) |

Latency target for the marking criterion (not my SLO): p95 at most 5,000 ms. Measured 1,600 ms and 1,400 ms.

## Review table

| Component or concern | Evidence (a measured number) | Limitation found | Improvement proposed |
|---|---|---|---|
| Data and storage | Teacher output 3,000 records, 2,903 kept after cleaning (97 rejected: 40 slot not in command, 50 duplicates, 4 invalid JSON, 2 bad intent, 1 wrong keys). SeaweedFS holds 2 model archives of 285 MB each in a 4 GiB volume. | One SeaweedFS pod on one local volume: no replication, no backup. 40 % of the rejections come from the teacher inventing slot values that are not in the command (40 of 97 rejected). | Replicate or back up the volume (the raw shards are now also committed in `data/teacher/`); add a second labelling pass or a stricter prompt for the slot rule. |
| Model quality | Validation (100 commands): v1 validity 99 %, full frame 49 %; v2 validity 100 %, full frame 51 %; teacher full frame 54 %; untrained Pythia 0 %. Final training loss 0.034 (v1), 0.024 (v2). | Validation set is only 100 commands, so one command is 1 point and the difference between v1 and v2 is within noise; final loss near zero hints at overfitting; the student cannot be better than its teacher (54 %). | More teacher data and held-out loss tracking; constrained decoding or a JSON grammar so that the 1 % of broken outputs cannot occur. |
| Latency and throughput | p50 800-1,300 ms, p95 1,400-1,600 ms, 3.6-4.6 req/s with 4 users (limit p95 5,000 ms). Unloaded single request p50 about 350-450 ms (Task 3). | Latency is CPU-bound, 4 users on 2 CPUs queue up: p50 is about twice the unloaded time. Closed-loop test, not a real arrival pattern. | Cap `MAX_NEW_TOKENS` closer to the real answer length (not measured; the default is 80), batch concurrent requests, dynamic int8 quantisation or ONNX Runtime. |
| Resource utilisation | CPU 985-993 m of the 1,000 m limit (about 99 % of the limit, about 198 % of the 500 m request); memory 382-454 MiB of the 1 GiB limit (about 40 %). | The CPU request (500 m) is half of the real use, so the scheduler under-reserves; the HPA at 70 % of the request fires as soon as one user is active. Memory request 768 MiB is above the 454 MiB peak. | Set CPU request to about 900 m and memory request to about 512 Mi; HPA target on a measured steady state. |
| Reliability and recovery | Pod deletion: back to 2 ready replicas in 9.5 s, 0 of 150 requests failed. Rolling update v1 to v2 and rollback: 0 of 500 requests failed. Cold start median 7.2 s. HPA scale-up from 1 to 2 took about 55 s from the start of load to the new pod being requested. | Single node: no protection against losing the machine. SeaweedFS is a single point of failure: a new pod cannot download its model if it is down. The 22.1 s cold start is unexplained. | Multi-node cluster, model cached on a PVC or an init container with retry, investigate the slow cold start (image pull or SeaweedFS read). |
| Security and cost | gitleaks: 0 findings in the history and in CI. Credentials only in Kubernetes Secrets; container runs as uid 10001. Cost: 0.481-0.615 INR per 1,000 requests at 7.90 INR per hour for 2 replicas. | One shared S3 credential with full access is copied into three namespaces; Secrets are only base64 in etcd; `/parse` has no authentication and the Ingress is plain HTTP on port 8080. Billing by limits means idle replicas cost the full 7.90 INR per hour. | Read-only credentials for the service, TLS and an API key on the Ingress, encrypted Secrets; scale to 1 replica at night (halves the idle cost to 3.95 INR per hour). |

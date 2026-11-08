# Setup guide (reproduce on another machine)

Tested on Fedora 43 (x86_64, 16 cores, 30 GB RAM). Everything runs locally; nothing is paid.
Progress and the problems met along the way are in `SETUP_LOG.md`.

## Versions used

| Component | Version |
|---|---|
| Docker | 29.8.1 |
| k3d | v5.9.0 (k3s v1.35.5+k3s1, includes Traefik and metrics-server) |
| kubectl | v1.37.1 |
| Ollama | 0.40.14, model `phi3.5:latest` (3.8B, Q4_0, digest `61819fb370a3…`) |
| SeaweedFS | image `chrislusf/seaweedfs:4.51` |
| Python (host) | 3.13.1; worker image `python:3.12-slim` |
| boto3 / botocore | 1.43.125 |

## 1. One-time host prerequisites

```bash
# Docker
sudo systemctl enable --now docker            # then log out/in if `docker ps` says permission denied
# k3d and kubectl
curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash
sudo dnf install kubernetes-client
# Ollama (systemd service), then the project's host setup (needs sudo)
curl -fsSL https://ollama.com/install.sh | sh
./scripts/setup_ollama.sh
```

`scripts/setup_ollama.sh` makes Ollama listen on all interfaces (so pods can reach it at
`host.k3d.internal:11434`), sets `OLLAMA_NUM_PARALLEL=1` (reproducible teacher output) and pulls `phi3.5`.

Port **8080** must be free on the host: the k3d load balancer binds it, and the load test uses it.

## 2. Build and deploy the infrastructure

```bash
make up        # check, cluster, namespaces, secrets, SeaweedFS, buckets, worker image
```

Each step is also its own target (`make help`) and is safe to re-run.

## 3. Teacher labelling (Task 1)

```bash
make label     # two workers in namespace pipeline; ~25 min; writes datasets/teacher/shard-{0,1}.jsonl
make status
```

The teacher settings are fixed in `worker/worker.py` (`temperature 0`, `seed 42`, `stop ["\n"]`) and the prompt
is `prompts/teacher_prompt.txt`. If the prompt changes, regenerate everything.

## 4. Clean the teacher output (Task 1)

```bash
make dataset   # worker/clean.py: datasets/teacher/shard-*.jsonl -> datasets/v1/train.jsonl + train.sha256
```

Prints the rejection counts and writes `results/clean_report.json`; local copies (including the
rejected records with reasons) are in `out/v1/`. The result is deterministic: running it again must give
the same SHA-256 (`cd out/v1 && sha256sum -c train.sha256`).

## 5. Train the student (Task 2)

Runs on the host CPU, outside the cluster. The first `make train` creates `.venv-train` from
`training/requirements.txt` (pinned versions, CPU-only PyTorch).

```bash
make train SUBSET=50                 # quick check that training runs (first 50 records; outputs in out/subset-test/)
make train                           # model v1, reads only training/config.yaml; writes training/loss.csv, out/models/v1/
make train-v2                        # model v2 (training/config_v2.yaml: one more epoch)
make publish-model VERSION=v1        # upload to s3://models/v1/ and verify the archive checksum
make publish-model VERSION=v2
make eval MODEL=out/models/v1 NAME=student_v1                  # predictions + score.py on the validation set -> results/
make eval MODEL=EleutherAI/pythia-70m NAME=base_pythia         # the untrained base model
python3 scripts/teacher_predict.py && python3 tools/score.py results/teacher_predictions.jsonl data/validation.jsonl --out results/teacher_validation.json
```

`make train` needs `data/v1/train.jsonl` (a copy of `datasets/v1/train.jsonl`, written by hand after `make dataset`:
`cp out/v1/train.* data/v1/`); the script refuses to run if it does not match `data/v1/train.sha256`.
`model.sha256` holds the SHA-256 of the archive `model-<version>.tar`; that archive is also the GitHub Release asset.

## 6. Inference service image (Task 3)

```bash
make service-image      # docker build of service/Dockerfile; every dependency is pinned in service/requirements.txt
make service-check      # API contract + FAULT_INJECT=1 -> results/service_api.txt
make service-limits     # 1 CPU / 1 GiB, 50 requests, peak memory -> results/service_limits.txt
```

The image contains no model weights. At start-up the service downloads `MODEL_URI` (for example `s3://models/v1`)
from `S3_ENDPOINT`, verifies `files.sha256`, loads the model and only then answers `/readyz` with 200.
The two check scripts run the container with host networking, so they use ports 18000 and 18001 on the host.

## 7. Deploy the service to Kubernetes (Task 4)

```bash
make deploy-app      # imports parser-service:1 into k3d, applies k8s/app.yaml (Deployment x2, Service, Ingress /parse, HPA 1-2 at 70% CPU)
curl -s -X POST localhost:8080/parse -H 'content-type: application/json' -d '{"text":"weather in paris tomorrow"}'
make app-evidence    # ~5 min: writes results/task4_*.txt
```

Models must already be in the `models` bucket (`make train`, which uploads, or `make publish-model`). The Deployment starts on `MODEL_URI=s3://models/v1/`; the rolling update test switches it to v2 and rolls back. Pods drain for 8 s (`preStop`) so the Ingress stops routing to them before they stop.

## 8. Tear down

```bash
make down
```

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Bind for 0.0.0.0:8080 failed: port is already allocated` | Another process/container holds 8080. Find it with `ss -ltnp \| grep 8080`, stop it, then `make cluster`. |
| Pods stuck in `ImagePullBackOff` for `teacher-worker:1` | The image is not in the cluster node. `make worker-image` (re-imports it). Needed again after any cluster re-creation. |
| Worker cannot reach Ollama (`HTTP 000` from a pod) | Ollama is bound to 127.0.0.1. Run `scripts/setup_ollama.sh`. Check with `ss -ltn \| grep 11434` (expect `*:11434`). If still failing, check firewalld for the Docker bridge. |
| `ollama serve` says port in use | Ollama already runs as the `ollama` systemd service. Configure it (above) instead of starting it by hand. |
| Training hangs or is extremely slow | The Hub checkpoint is float16, which is very slow on CPU. `train.py` and `predict.py` force float32; keep it that way. |
| Upload to `models` fails with `InternalError` | SeaweedFS ran out of volume slots (each bucket pre-allocates 7). `-volume.max` is 40 in `k8s/seaweedfs.yaml`; re-apply it. |
| Disk full while pulling images | Free space on `/`; Docker images and the k3d node need a few GB. |

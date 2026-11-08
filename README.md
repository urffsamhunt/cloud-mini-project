# Command parser: distilling phi3.5 into Pythia-70M, deployed on a local k3d cluster

CS3081 Cloud Computing mini project. The teacher `phi3.5` (Ollama, temperature 0, seed 42) labels 3,000 commands; the student `EleutherAI/pythia-70m` is fine-tuned on those replies (sequence-level distillation) and served by a FastAPI service on Kubernetes (k3d), with the model files in SeaweedFS object storage. The report is `report/report.pdf`; the evidence is in `results/`.

The model files are **not** in Git. They are GitHub Release assets: `model-v1` and `model-v2` (`model-<v>.tar`, its SHA-256 is in `release/model-<v>.sha256`). The deployed model is **v2**.

## Prerequisites

Docker, k3d, kubectl, Python 3.12+, curl, openssl, GNU make. For the teacher run also Ollama with `phi3.5`; for the load test nothing else (Locust is installed in a virtual environment). Full list with versions and troubleshooting: `docs/SETUP.md`; every step that was run is logged in `docs/SETUP_LOG.md`.

## Build and deploy (from a fresh clone)

```bash
git clone https://github.com/urffsamhunt/cloud-mini-project.git
cd cloud-mini-project
make up        # k3d cluster, SeaweedFS, buckets, models (from the GitHub Release), service image, Deployment/Service/Ingress/HPA
```

Port 8080 on the host must be free. `make up` takes about 3 minutes plus the download of the two model archives (570 MB). Then:

```bash
curl -s -X POST localhost:8080/parse -H 'content-type: application/json' -d '{"text":"set an alarm for seven thirty am tomorrow"}'
```

## Test

```bash
pip install -r requirements-dev.txt
make lint                 # ruff
make test                 # 13 unit tests
python3 tools/nacl_sim.py network/nacl.json network/packets_sample.jsonl --check
make service-check        # API contract, FAULT_INJECT (needs make up first; uses the image on the host)
make service-limits       # 50 requests at 1 CPU / 1 GiB, peak memory
make app-evidence         # Task 4: endpoints while loading, recovery, rolling update + rollback, cold start x3 (about 15 min)
./scripts/task4_scaling.sh  # Task 4: HPA 1 -> 2 -> 1 (about 10 min)
make loadtest             # Task 7: Locust, 4 users, 2 minutes (standard command), kubectl top sampling
```

CI (`.github/workflows/ci.yml`): secret scan, lint, unit tests, evaluation of the Release model on `data/validation.jsonl`, quality gate `--min-validity 95`. Run it manually with `model_source = untrained` to see the gate fail.

## Reproduce the data and the models (optional, slow)

```bash
make label        # Task 1: two labelling workers in namespace pipeline (needs Ollama on the host; about 20 min)
make dataset      # clean the shards, write datasets/v1/train.jsonl and train.sha256
make train-env && make train            # Task 2: v1 on the CPU (about 6 min); make train SUBSET=50 for a quick check
make train-v2 && make publish-model VERSION=v2
make eval MODEL=out/models/v1 NAME=student_v1
```

`make help` lists every target.

## Tear down

```bash
make down         # deletes the k3d cluster and everything in it
```

## Layout

| Path | Content |
|---|---|
| `prompts/teacher_prompt.txt` | teacher prompt |
| `worker/` | labelling worker (`worker.py`), cleaning (`clean.py`), Dockerfile |
| `training/` | `config.yaml` (v1), `config_v2.yaml`, `train.py`, `predict.py`, `loss.csv`, `loss_v2.csv` |
| `service/` | FastAPI service and Dockerfile |
| `k8s/`, `cluster/` | manifests, `k3d.yaml` |
| `network/` | `subnets.md`, `nacl.json`, extra test packets |
| `tests/`, `.github/workflows/ci.yml` | unit tests, CI |
| `scripts/` | setup, secrets, bucket, evidence and load-test scripts |
| `data/` | the kit data, `teacher/` (raw teacher shards) and `v1/` (cleaned training set) |
| `results/` | all evidence: scores, predictions, Locust files, Task 4 logs, `task7_analysis.md`, `ci_runs.md` |
| `tools/` | `score.py`, `locustfile.py`, `nacl_sim.py` from the student kit (unchanged) |
| `AI_USE.md` | use of AI tools |

Data: commands from SLURP (Bastianelli et al., EMNLP 2020), CC BY 4.0, https://github.com/pswietojanski/slurp.

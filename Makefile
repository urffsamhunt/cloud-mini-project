# Reproducible setup for the cloud mini project.  Run `make help`.
# Targets run in order and are idempotent; do not use `make -j`.
.RECIPEPREFIX = >
SHELL := /bin/bash
CLUSTER ?= cloud
CONFIG ?= training/config.yaml
PY_TRAIN := .venv-train/bin/python
.NOTPARALLEL:
.PHONY: help check cluster namespaces secrets seaweedfs buckets worker-image up label dataset train-env train train-v2 eval publish-model service-image service-check service-limits deploy-app app-evidence status down

help: ## list targets
> @grep -E '^[a-z0-9-]+:.*## ' Makefile | awk -F':.*## ' '{printf "  make %-13s %s\n", $$1, $$2}'

check: ## verify tools, Docker, port 8080 and Ollama
> @for t in docker k3d kubectl python3 openssl curl; do command -v $$t >/dev/null || { echo "missing tool: $$t (see docs/SETUP.md)"; exit 1; }; done
> @docker info >/dev/null 2>&1 || { echo "Docker daemon is not running (sudo systemctl enable --now docker)"; exit 1; }
> @if ss -ltn | grep -qE ':8080\b' && ! k3d cluster list $(CLUSTER) >/dev/null 2>&1; then echo "port 8080 is already in use; free it before creating the cluster"; exit 1; fi
> @curl -s -m 5 localhost:11434/api/tags | grep -q phi3.5 && echo "ollama: phi3.5 available" || echo "WARNING: Ollama/phi3.5 not reachable; needed only for 'make label' (run scripts/setup_ollama.sh)"

cluster: ## create the k3d cluster from cluster/k3d.yaml
> k3d cluster list $(CLUSTER) >/dev/null 2>&1 || k3d cluster create --config cluster/k3d.yaml
> kubectl wait --for=condition=Ready node --all --timeout=180s

namespaces: ## create namespaces data, pipeline, app
> kubectl apply -f k8s/namespaces.yaml

secrets: ## generate S3 credentials as Kubernetes Secrets (never in Git)
> ./scripts/create_secrets.sh

seaweedfs: ## deploy SeaweedFS (S3 object storage) in namespace data
> kubectl apply -f k8s/seaweedfs.yaml
> kubectl -n data rollout status deploy/seaweedfs --timeout=300s

buckets: ## create buckets datasets and models, upload commands_pool.jsonl
> ./scripts/init_buckets.sh

worker-image: ## build the teacher worker image and import it into the cluster
> docker build -q -t teacher-worker:1 -f worker/Dockerfile .
> k3d image import teacher-worker:1 -c $(CLUSTER)

up: check cluster namespaces secrets seaweedfs buckets worker-image ## everything except the teacher run

label: ## run the 2 teacher workers and wait (restarts the job from scratch)
> kubectl -n pipeline delete job teacher-labelling --ignore-not-found
> kubectl apply -f k8s/teacher-job.yaml
> kubectl -n pipeline wait --for=condition=complete job/teacher-labelling --timeout=3h

dataset: ## clean the teacher shards -> datasets/v1/train.jsonl + train.sha256 (+ results/clean_report.json)
> ./scripts/with_s3.sh .venv/bin/python -I worker/clean.py

train-env: ## create the CPU-only training environment (.venv-train, pinned versions)
> [ -x $(PY_TRAIN) ] || python3 -m venv .venv-train
> .venv-train/bin/pip install -q -r training/requirements.txt

train: train-env ## fine-tune the student on CPU; reads only training/config.yaml (SUBSET=50 for a quick check)
> $(PY_TRAIN) -I training/train.py --config $(CONFIG) $(if $(SUBSET),--subset $(SUBSET),)

train-v2: ## train the second model version (training/config_v2.yaml)
> $(MAKE) train CONFIG=training/config_v2.yaml

eval: train-env ## score a model on the validation set: make eval MODEL=out/models/v1 NAME=student_v1
> $(PY_TRAIN) -I training/predict.py --model $(MODEL) --data data/validation.jsonl --out results/$(NAME)_predictions.jsonl
> python3 tools/score.py results/$(NAME)_predictions.jsonl data/validation.jsonl --out results/$(NAME)_score.json

publish-model: ## upload a trained model to the models bucket and verify: make publish-model VERSION=v1
> ./scripts/with_s3.sh $(PY_TRAIN) -I training/upload_model.py out/models/$(VERSION) $(VERSION)

service-image: ## build the inference service image (no model weights inside)
> docker build -q -t parser-service:1 -f service/Dockerfile .

service-check: ## test the API contract and FAULT_INJECT on the image (needs the models bucket)
> ./scripts/with_s3.sh scripts/check_service_api.sh

service-limits: ## run the image at 1 CPU / 1 GiB, send 50 requests, report peak memory
> ./scripts/with_s3.sh scripts/check_service_limits.sh

deploy-app: service-image ## import the service image into k3d and deploy it to namespace app
> k3d image import parser-service:1 -c $(CLUSTER)
> kubectl apply -f k8s/app.yaml
> kubectl -n app rollout status deploy/parser --timeout=300s

app-evidence: ## Task 4 tests: load balancing, pod deletion, rolling update + rollback, cold start x3
> ./scripts/task4_evidence.sh

status: ## show pods and jobs
> kubectl get pods -A
> kubectl -n pipeline get jobs

down: ## delete the cluster (and everything in it)
> k3d cluster delete $(CLUSTER)

# Setup log

Chronological record of what was done, what broke and how it was fixed. Append to it as work continues.
Commands that matter for reproduction live in `Makefile` and `docs/SETUP.md`.

## Task 1: object storage and teacher labelling

| Step | What | Where |
|---|---|---|
| 1 | Read the assignment PDF; decided on a fully local stack: k3d, SeaweedFS, Ollama (phi3.5). Azure, SST and LM Studio rejected: the handout requires a local k3d cluster, SeaweedFS and an Ollama teacher. | |
| 2 | Wrote the teacher prompt (8 intents, 3 slot rules, 12 few-shot examples; none from `validation.jsonl`). | `prompts/teacher_prompt.txt` |
| 3 | Tested the prompt: 6/10 replies valid at first, because phi3.5 appended explanations after the JSON. Added `"stop": ["\n"]` to the generation options. Re-test: 20/20 valid and 20/20 deterministic (temperature 0, seed 42), about 0.3 s per command. | `scripts/test_teacher.py` |
| 4 | Wrote the sharded worker (`SHARD_INDEX`, `SHARD_COUNT`, line number mod count, raw reply stored unmodified, resumable, optional S3 upload). Tested locally with 2 shards x 5 commands: disjoint ids. | `worker/worker.py` |
| 5 | Wrote a personal test page (voice/text to Ollama, toy clock and calendar). Not part of the graded pipeline. | `playground/index.html` |
| 6 | Installed Docker daemon, k3d, kubectl; created cluster. | `cluster/k3d.yaml` |
| 7 | **Problem:** `Bind for 0.0.0.0:8080 failed`. A `fluent-bit` container from another project held port 8080. **Fix:** stopped that container. | |
| 8 | Created namespaces `data`, `pipeline`, `app`. | `k8s/namespaces.yaml` |
| 9 | Deployed SeaweedFS 4.51 (master, volume, filer, S3 gateway in one pod, 4 Gi local-path volume). S3 keys are generated at deploy time and stored only as Kubernetes Secrets. | `k8s/seaweedfs.yaml`, `scripts/create_secrets.sh` |
| 10 | Created buckets `datasets` and `models`; uploaded `commands_pool.jsonl` (197,541 bytes). | `scripts/init_buckets.py`, `scripts/init_buckets.sh` |
| 11 | Built and imported the worker image (`teacher-worker:1`, 161 MB, boto3 pinned). Validated the Job manifest. | `worker/Dockerfile`, `k8s/teacher-job.yaml` |
| 12 | **Problem:** pods could not reach Ollama (`HTTP 000`). Ollama listened on 127.0.0.1 only. | |
| 13 | **Problem:** `ollama serve` in a terminal failed with port in use: Ollama already runs as a systemd service. **Fix:** a systemd drop-in with `OLLAMA_HOST=0.0.0.0` and `OLLAMA_NUM_PARALLEL=1`, then restart the service. After that, pods reached Ollama (HTTP 200). | `scripts/setup_ollama.sh` |
| 14 | **Problem:** worker pods in `ImagePullBackOff`; `crictl images` in the k3d node did not list `teacher-worker:1`. **Fix:** `k3d image import teacher-worker:1 -c cloud` again, deleted the stuck pods; the Job recreated them. Cause of the missing image not determined. | `make worker-image` |
| 15 | Two workers running in `pipeline`, each handling 1,500 commands (shard 0 and shard 1), about 200 commands per 2.5 minutes. | `k8s/teacher-job.yaml` |
| 16 | Wrote the `Makefile` (`make up`, `make label`, `make down`, ...) and this documentation. Ran the idempotent targets (`namespaces`, `secrets`, `seaweedfs`, `buckets`) against the live cluster: all succeeded, nothing changed. `make cluster`, `worker-image` and `label` were **not** run from the Makefile, so they are untested. | `Makefile` |

| 17 | Labelling Job finished: 2/2 completed in about 21 minutes. Both shards uploaded to `datasets/teacher/`. Saved the pod logs and Job status into `results/`. | `results/teacher-shard-*.log`, `results/teacher-job-status.yaml` |
| 18 | Wrote `worker/clean.py` and `scripts/with_s3.sh` (port-forward + credentials helper). Ran it: input 3000, (a) invalid JSON 4, (b) wrong keys 1, (c) bad intent 2, (d) slot not in command 40, (e) duplicates 50, kept 2903. SHA-256 `dfcdc41d…6671f`. Second run gave identical bytes; `sha256sum -c` OK; every pool id appears exactly once across kept and rejected records. Uploaded `datasets/v1/train.jsonl` and `train.sha256`. | `worker/clean.py`, `results/clean_report.json`, `make dataset` |

## Task 2: training the student

| Step | What | Where |
|---|---|---|
| 19 | Created the training environment (`.venv-train`): CPU-only torch 2.15.0, transformers 5.22.1, pinned in `training/requirements.txt`. Copied the cleaned dataset to `data/v1/` (checksum verified at training start). | `training/requirements.txt` |
| 20 | Wrote `training/config.yaml`, `training/train.py`, `training/predict.py`. Format: `Command: <text>\nJSON: <teacher reply>`, loss only on the reply, AdamW lr 2e-4, batch 16, 5 epochs, seed 42, max length 128 (longest example is 65 tokens). | `training/` |
| 21 | **Problem:** the 50-example test ran for more than 10 minutes without finishing an epoch. Profiling showed the backward pass was about 9 s for a tiny batch. **Cause:** the Hub checkpoint is float16, and float16 matrix multiplies are very slow on this CPU. **Fix:** load with `dtype=torch.float32`. The test then took 19 s. | `training/train.py` |
| 22 | Trained v1 on 1,500 records: about 66 s per epoch; loss 0.498, 0.253, 0.152, 0.076, 0.034. Saved model, tokenizer, `version.json`, a deterministic archive `model-v1.tar` and `model.sha256` (`e7b7b823…f85963`). | `training/loss.csv`, `out/models/v1/` |
| 23 | Validation (100 commands, `tools/score.py`): student v1 validity 99, intent 85, date 82, time 84, place 86, full frame 49. Untrained Pythia-70M: all 0. Teacher (phi3.5, same prompt and settings): validity 99, intent 85, date 80, time 87, place 87, full frame 54. | `results/*_predictions.jsonl`, `results/*_score.json`, `results/teacher_validation.json` |
| 24 | **Problem:** uploading to the `models` bucket failed with `InternalError`. SeaweedFS log: no free volumes. Each bucket pre-allocates 7 volumes and `-volume.max` was 12. **Fix:** raised it to 40 and re-applied (the data volume persisted). Uploaded `models/v1/` and verified the archive checksum after download. | `k8s/seaweedfs.yaml`, `make publish-model` |
| 25 | Trained v2 (same settings, 6 epochs): loss 0.485, 0.295, 0.179, 0.106, 0.054, 0.024. Uploaded to `models/v2/` and verified (`a775ecc5…eba1`). Validation: validity 100, intent 85, date 79, time 93, place 87, full frame 51. | `training/loss_v2.csv`, `results/student_v2_score.json` |
| 26 | Initialised the git repository (branch `main`) and made the first commit: 53 files, about 1 MB. Model files, `out/` and virtual environments are excluded by `.gitignore`. A scan for key-like strings found none. Chosen visibility: public. | `.gitignore` |

## Task 3: inference service

| Step | What | Where |
|---|---|---|
| 27 | Wrote the FastAPI service: `POST /parse`, `GET /healthz`, `GET /readyz` (503 until loaded). Config from `MODEL_URI`, `MODEL_VERSION`, `S3_ENDPOINT`, `MAX_NEW_TOKENS` (+ `FAULT_INJECT`); credentials from the environment (a Secret in the cluster). Output is checked against `schema.json`; invalid output gives HTTP 500 `{"error": "invalid_model_output"}`. The model is downloaded in a background thread at start-up and checked against `files.sha256`; a failed load exits the process so Kubernetes restarts the pod. Torch threads follow the container's CPU quota. | `service/app.py` |
| 28 | Built the image: `python:3.12.16-slim`, CPU-only torch, all 50 dependencies pinned (resolved inside a container and frozen), runs as a non-root user, no weights. Size 1.31 GB (limit 2 GB). | `service/Dockerfile`, `service/requirements.txt`, `.dockerignore` |
| 29 | **Problem:** the first limits test failed: port 8000 on the host is used by another program (answers HTTP 401). The test scripts now use ports 18000 and 18001. | `scripts/check_service_limits.sh` |
| 30 | Changed response bodies to Python's default `json.dumps` format (`"error": "invalid_model_output"` with a space), to match how the handout writes them. | `service/app.py` |
| 31 | Limits test at 1 CPU and 1 GiB without swap: model download 285 MB, ready 5 s after start; 50 sequential requests gave 49 x HTTP 200 and 1 x HTTP 500 (the validation caught one invalid model output); p50 351 ms, p95 498 ms; peak memory (cgroup `memory.peak`) 811,036,672 bytes (773 MiB, including page cache from the downloaded files; `docker stats` showed 350 MiB in use afterwards); not OOM-killed. | `results/service_limits.txt` |
| 32 | API check: `/healthz` 200, `/readyz` 503 then 200, headers `X-Model-Version` and `X-Served-By` present, empty text gives 422, `FAULT_INJECT=1` gives HTTP 500 with the exact error body. | `results/service_api.txt` |

Decisions in `clean.py`: records are counted under the first rule they break, in the order (a) to (d); duplicates (exact same command text) are removed afterwards, only among records that passed (a) to (d), keeping the smallest id. Slot values are compared with the command as an exact (case-sensitive) substring. Local-file mode (no `S3_ENDPOINT`) is untested.

33. Task 4 manifests: `k8s/app.yaml` (Deployment 2 replicas, requests 500m/768Mi, limits 1 CPU/1Gi, startup/liveness/readiness probes, maxUnavailable 0, Service, Traefik Ingress for `/parse` and `/readyz`, HPA 1-2 at 70% CPU). `k3d image import parser-service:1 -c cloud` then `kubectl apply`: both pods Ready in about 20 s; `curl localhost:8080/parse` returned 200 with `X-Served-By`. Ran.
34. `scripts/task4_evidence.sh` (Make target `app-evidence`). First run showed 3 x HTTP 502 and 1 x 000 during the rolling update: Traefik kept sending requests to a pod that had started terminating. Fix: `preStop: sleep 8` and `terminationGracePeriodSeconds: 30`. Rerun: rolling update v1 -> v2 -> rollback, 500 requests, all 200 (456 served by v1, 44 by v2); pod deletion, 150 requests all 200, two ready pods again after 9.5 s; 200 requests split 100/100 between the two pods; cold start (scale 0 -> 1 until Ready) 7.2 s, 7.1 s, 22.1 s, median 7.2 s. Ran; evidence in `results/task4_*.txt`. The load-balancing test itself showed 1 x 502 and 1 x 000 when run right after a manifest rollout, while the old pod was still draining; the script now waits for a settled state first, and the stored load-balancing result is a rerun on a settled deployment (the other three files come from the full run).
35. Makefile targets `deploy-app`, `app-evidence` added (not run through `make`; the commands were run directly).
36. Task 5: `network/subnets.md` (table, working, NACL tables, half-page explanation), `network/nacl.json`, `network/packets_extra.jsonl` (23 own test packets). `tools/nacl_sim.py --check`: sample 6/6, extra 23/23. Two of my first expectations were wrong (outbound 8000 to non-app addresses and 8001 to the app subnet are allowed by the reply rule 1024-65535); documented as a known limitation in `subnets.md`. Ran. No cluster involvement.
37. Task 6 tests and lint: `tests/` (13 pytest tests: cleaning rules, service validation and probes, prompt format, `score.py` gate, NACL), `ruff.toml` (E, F, W, I; E501 and E741 ignored; `tools/` excluded because it is the instructor's kit), `requirements-dev.txt`, `pytest.ini`. Ran in a scratch venv: `ruff check .` clean, 13 passed. Ruff changed the import order in `service/app.py` and split two semicolon lines in `training/train.py`; behaviour is unchanged, but the service image was built before this and has not been rebuilt.
38. `.github/workflows/ci.yml`: secret-scan (gitleaks action) next to lint; then unit-tests, evaluate (downloads the model from the GitHub Release, checks it against `release/model-<v>.sha256`, runs `training/predict.py` and `tools/score.py`), quality-gate (`score.py --min-validity 95`). Manual run with `model_source = untrained` evaluates the untrained Pythia so the gate fails. NOT RUN: only YAML syntax checked; needs the GitHub Release and a push.
39. gitleaks run locally with the Docker image over the 5 existing commits: no leaks.
40. `scripts/fetch_models.py` + Makefile `models`, `lint`, `test`; `make up` now = check, cluster, namespaces, secrets, seaweedfs, buckets, models, worker-image, deploy-app. NOT RUN: `make up` from a fresh clone needs the Release to exist (published models are fetched from it), and the test deletes the current cluster. Only `make -n up` was checked.
41. `AI_USE.md` written (draft; the student has to add their own corrections at the end).
42. Published Releases `model-v1` and `model-v2` (by the user; asset digests on GitHub equal `release/model-<v>.sha256`). Pushed to GitHub (git's configured `credential-secret` helper does not exist on this machine, so the push used `-c credential.helper='!gh auth git-credential'`). CI run 1 (release model-v1): all five jobs green, gitleaks reported nothing, CI scores equal the local ones (99/85/49). CI run 2 (`model_source=untrained`): only the quality gate failed. Links in `results/ci_runs.md`. Ran on GitHub.

## Open items

- Task 1 report: counts table and a half-page on sharding.
- Task 4 left: HPA scale-up under load (do it with the Task 7 Locust run), single-node limitation statement in the report, `kubectl top pods` under load.
- Task 3 left: unit tests (Task 6).
- Task 2: GitHub Release asset (repo is pushed to GitHub; `gh release create` was blocked by the permission classifier because it makes public files, so the user has to run it or allow it), report text (loss table, three-model comparison, half-page distillation explanation).
- Task 6: publish the Releases, push, run the workflow twice (release model: passes; untrained: fails at the gate) and keep the links; test `make down` then `make up` from a fresh clone (two commands after the clone).
- Final README.md must list build, deploy, test and teardown commands (the current README.md is the original student kit file).

## Known limitations

- Worker progress is stored in the pod's filesystem until the end of the run, so a container restart loses it (a pod deletion loses it too); the shard is then redone from the start.
- `kubectl apply` of the namespaces warns once about a missing annotation because they were first created with `kubectl create`. Harmless.
- The cluster is a single node on one laptop; it does not show fault tolerance across machines.

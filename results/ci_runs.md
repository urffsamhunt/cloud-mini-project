# CI runs (GitHub Actions, workflow `ci`)

| Run | Model | Result | Link |
|---|---|---|---|
| push of `e4347e2` | release `model-v1` | all 5 jobs green; validity 99, intent 85, full_frame 49 (same as the local scores) | https://github.com/urffsamhunt/cloud-mini-project/actions/runs/42459095876 |
| manual, `model_source = untrained` | untrained EleutherAI/pythia-70m | secret-scan, lint, unit-tests, evaluate green; **quality-gate failed** (validity below 95) | https://github.com/urffsamhunt/cloud-mini-project/actions/runs/42459268412 |

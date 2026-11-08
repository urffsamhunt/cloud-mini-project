#!/usr/bin/env bash
# Rolling update + rollback under Locust load, with the command V049 removed from the command list.
# Why: model v1 answers V049 with broken JSON (HTTP 500 invalid_model_output, 1 in 100 requests while v1 serves),
# which Locust counts as a failure. Without V049 every failure left would come from the rollout itself.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p out
python3 - <<'PY'
import json
rows = [l for l in open("data/validation.jsonl", encoding="utf-8") if l.strip() and json.loads(l)["id"] != "V049"]
open("out/validation_without_V049.jsonl", "w", encoding="utf-8").writelines(rows)
print(len(rows), "commands")
PY
SECTIONS=rollout ROLLOUT_NAME=task4_rollout_without_V049 LOADTEST_TEXTS=out/validation_without_V049.jsonl ./scripts/task4_evidence.sh

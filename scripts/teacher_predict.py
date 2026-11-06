"""Run the teacher (same prompt and settings as the labelling job) on a labelled file.

Writes predictions in the format tools/score.py expects. Usage:
  python3 scripts/teacher_predict.py [--data data/validation.jsonl] [--out results/teacher_predictions.jsonl]
"""
import argparse
import json
import os
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Identical to worker/worker.py: these settings define the teacher.
OPTIONS = {"temperature": 0, "seed": 42, "num_predict": 128, "stop": ["\n"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data" / "validation.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "results" / "teacher_predictions.jsonl"))
    ap.add_argument("--host", default=os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    ap.add_argument("--model", default="phi3.5")
    a = ap.parse_args()

    template = (ROOT / "prompts" / "teacher_prompt.txt").read_text()
    rows = [json.loads(l) for l in Path(a.data).read_text().splitlines() if l.strip()]
    out, t0 = [], time.time()
    for r in rows:
        body = json.dumps({"model": a.model, "prompt": template.replace("{command}", r["text"]),
                           "stream": False, "options": OPTIONS}).encode()
        req = urllib.request.Request(f"{a.host}/api/generate", body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            out.append({"id": r["id"], "prediction": json.load(resp)["response"]})
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("".join(json.dumps(o) + "\n" for o in out))
    print(f"{len(out)} teacher predictions in {time.time() - t0:.0f}s -> {a.out}")


if __name__ == "__main__":
    main()

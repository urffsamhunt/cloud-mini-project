"""Teacher-labelling worker (Task 1).

Reads SHARD_INDEX and SHARD_COUNT, takes every command whose 0-based line number
n satisfies n % SHARD_COUNT == SHARD_INDEX, sends it to the teacher (Ollama,
temperature 0, seed 42) and writes one line per command:
    {"id": ..., "text": ..., "teacher_raw": "<the teacher's exact reply>"}

Local mode (default): reads COMMANDS_PATH, writes OUT_DIR/teacher/shard-<i>.jsonl.
S3 mode (S3_ENDPOINT set): downloads datasets/commands_pool.jsonl from the object
store and uploads datasets/teacher/shard-<i>.jsonl when finished. Credentials come
from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in the environment (a Kubernetes
Secret in the cluster), never from the repository.

The output file is appended to line by line, and ids already present are skipped,
so a crashed worker can simply be restarted.
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

SHARD_INDEX = int(os.environ["SHARD_INDEX"])
SHARD_COUNT = int(os.environ["SHARD_COUNT"])
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
MODEL = os.environ.get("TEACHER_MODEL", "phi3.5")
PROMPT_PATH = Path(os.environ.get("PROMPT_PATH", "prompts/teacher_prompt.txt"))
COMMANDS_PATH = Path(os.environ.get("COMMANDS_PATH", "data/commands_pool.jsonl"))
OUT_DIR = Path(os.environ.get("OUT_DIR", "out"))
S3_ENDPOINT = os.environ.get("S3_ENDPOINT")
BUCKET = os.environ.get("DATASETS_BUCKET", "datasets")
LIMIT = int(os.environ.get("LIMIT", "0"))  # for testing: stop after this many commands

# These must stay identical for every worker and for the Task 2 teacher evaluation.
OPTIONS = {"temperature": 0, "seed": 42, "num_predict": 128, "stop": ["\n"]}


def s3():
    import boto3
    return boto3.client("s3", endpoint_url=S3_ENDPOINT)


def ask_teacher(prompt):
    body = json.dumps({"model": MODEL, "prompt": prompt, "stream": False, "options": OPTIONS}).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/generate", body, {"Content-Type": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.load(r)["response"]
        except Exception as e:  # Ollama busy or restarting: back off and retry
            print(f"teacher error ({e}); retry {attempt + 1}/5", file=sys.stderr, flush=True)
            time.sleep(2 ** attempt)
    raise RuntimeError("teacher unreachable")


def main():
    if not 0 <= SHARD_INDEX < SHARD_COUNT:
        sys.exit("SHARD_INDEX must satisfy 0 <= SHARD_INDEX < SHARD_COUNT")
    template = PROMPT_PATH.read_text()
    key = f"teacher/shard-{SHARD_INDEX}.jsonl"
    out_path = OUT_DIR / key
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if S3_ENDPOINT:
        lines = s3().get_object(Bucket=BUCKET, Key="commands_pool.jsonl")["Body"].read().decode().splitlines()
    else:
        lines = COMMANDS_PATH.read_text().splitlines()

    done = set()
    if out_path.exists():
        done = {json.loads(l)["id"] for l in out_path.read_text().splitlines() if l.strip()}

    mine = [json.loads(l) for n, l in enumerate(lines) if n % SHARD_COUNT == SHARD_INDEX]
    if LIMIT:
        mine = mine[:LIMIT]
    print(f"shard {SHARD_INDEX}/{SHARD_COUNT}: {len(mine)} commands, {len(done)} already done", flush=True)

    with out_path.open("a") as f:
        for i, row in enumerate(mine, 1):
            if row["id"] in done:
                continue
            raw = ask_teacher(template.replace("{command}", row["text"]))
            f.write(json.dumps({"id": row["id"], "text": row["text"], "teacher_raw": raw}) + "\n")
            f.flush()
            if i % 50 == 0:
                print(f"shard {SHARD_INDEX}: {i}/{len(mine)}", flush=True)

    if S3_ENDPOINT:
        s3().upload_file(str(out_path), BUCKET, key)
        print(f"uploaded s3://{BUCKET}/{key}", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()

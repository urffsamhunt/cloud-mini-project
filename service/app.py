"""Command-parser inference service (Task 3).

POST /parse   {"text": "..."}  -> the four-key JSON object, headers X-Model-Version and X-Served-By
GET  /healthz                  -> 200 while the process is alive
GET  /readyz                   -> 503 until the model is loaded, 200 afterwards

Configuration (environment): MODEL_URI (e.g. s3://models/v1), MODEL_VERSION, S3_ENDPOINT, MAX_NEW_TOKENS.
FAULT_INJECT=1 replaces the model output with the text "not json" before it is validated (for testing).
S3 credentials come from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (a Kubernetes Secret in the cluster).
"""
import hashlib
import json
import logging
import math
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field

from common import prompt_for

log = logging.getLogger("service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

MODEL_URI = os.environ.get("MODEL_URI", "")
MODEL_VERSION = os.environ.get("MODEL_VERSION", "unknown")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "")
MAX_NEW_TOKENS = int(os.environ.get("MAX_NEW_TOKENS", "80"))
POD_NAME = os.environ.get("HOSTNAME") or socket.gethostname()

SCHEMA_PATH = Path(__file__).with_name("schema.json")
if not SCHEMA_PATH.exists():
    SCHEMA_PATH = Path(__file__).resolve().parent.parent / "data" / "schema.json"
VALIDATOR = Draft202012Validator(json.loads(SCHEMA_PATH.read_text())["json_schema"])

state = {"model": None, "tok": None}
lock = threading.Lock()   # one generation at a time; the model is small and the CPU is limited


def validate(raw):
    """Return the parsed object if raw is valid JSON that matches schema.json, else None."""
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return obj if VALIDATOR.is_valid(obj) else None


def cpu_limit():
    """CPUs this container may use (cgroup quota if set), so torch does not oversubscribe."""
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max":
            return max(1, math.ceil(int(quota) / int(period)))
    except (OSError, ValueError):
        pass
    return os.cpu_count() or 1


def download_model(dest):
    import boto3
    bucket, _, prefix = MODEL_URI.removeprefix("s3://").partition("/")
    prefix = prefix.strip("/") + "/"
    s3 = boto3.client("s3", endpoint_url=S3_ENDPOINT or None)
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
    keys = [o["Key"] for p in pages for o in p.get("Contents", [])]
    wanted = [k for k in keys if not k.endswith((".tar", "model.sha256"))]
    if not any(k.endswith("model.safetensors") for k in wanted):
        raise RuntimeError(f"no model found under {MODEL_URI}")
    total = 0
    for k in wanted:
        target = dest / k[len(prefix):]
        s3.download_file(bucket, k, str(target))
        total += target.stat().st_size
    log.info("downloaded %d files (%.1f MB) from %s", len(wanted), total / 1e6, MODEL_URI)
    listing = dest / "files.sha256"                       # integrity check against the recorded checksums
    for line in listing.read_text().splitlines():
        digest, name = line.split()
        h = hashlib.sha256((dest / name).read_bytes()).hexdigest()
        if h != digest:
            raise RuntimeError(f"checksum mismatch for {name}")
    log.info("checksums verified")


def load_model():
    t0 = time.time()
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        torch.set_num_threads(cpu_limit())
        dest = Path(tempfile.mkdtemp(prefix="model-"))
        download_model(dest)
        tok = AutoTokenizer.from_pretrained(dest)
        model = AutoModelForCausalLM.from_pretrained(dest, dtype=torch.float32).eval()
        state["tok"], state["model"] = tok, model
        log.info("model %s ready after %.1f s (threads=%d)", MODEL_VERSION, time.time() - t0, torch.get_num_threads())
    except Exception:
        log.exception("model failed to load; exiting so that Kubernetes restarts the pod")
        os._exit(1)


app = FastAPI(title="command parser")


@app.on_event("startup")
def startup():
    threading.Thread(target=load_model, daemon=True).start()


def generate(text):
    import torch
    tok, model = state["tok"], state["model"]
    enc = tok(prompt_for(text), return_tensors="pt")
    with lock, torch.inference_mode():
        out = model.generate(**enc, max_new_tokens=MAX_NEW_TOKENS, do_sample=False,
                             pad_token_id=tok.pad_token_id or tok.eos_token_id, eos_token_id=tok.eos_token_id)
    text_out = tok.decode(out[0, enc.input_ids.shape[1]:], skip_special_tokens=True)
    return text_out.split("\n")[0].strip()


def json_response(obj, status=200, headers=None):
    # Same formatting as Python's json.dumps ("key": value), which is how the handout writes its examples.
    return Response(content=json.dumps(obj), status_code=status, media_type="application/json", headers=headers)


class ParseIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@app.post("/parse")
def parse(body: ParseIn):
    headers = {"X-Model-Version": MODEL_VERSION, "X-Served-By": POD_NAME}
    if state["model"] is None:
        return json_response({"error": "model_not_ready"}, 503, headers)
    raw = generate(body.text)
    if os.environ.get("FAULT_INJECT") == "1":
        raw = "not json"
    obj = validate(raw)
    if obj is None:
        return json_response({"error": "invalid_model_output"}, 500, headers)
    return json_response({k: obj[k] for k in ("intent", "date", "time", "place")}, 200, headers)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    if state["model"] is None:
        return JSONResponse({"status": "loading"}, status_code=503)
    return {"status": "ready"}

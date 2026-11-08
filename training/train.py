"""Sequence-level distillation: fine-tune Pythia-70M on the teacher's replies (Task 2).

Each training example is
    Command: <the command>
    JSON: <the teacher's JSON reply>
The student learns to produce the teacher's output given the command; no logits are used.

Usage: python training/train.py [--config training/config.yaml] [--subset N]
All hyper-parameters come from the config file. --subset N trains on the first N records only
(a quick check that the pipeline runs); its outputs go to out/subset-test/ and never touch
training/loss.csv or the real model directory.
"""
import argparse
import csv
import hashlib
import io
import json
import random
import sys
import tarfile
import time
from importlib.metadata import version as pkg_version
from pathlib import Path

import numpy as np
import torch
import yaml
from transformers import AutoModelForCausalLM, AutoTokenizer, get_linear_schedule_with_warmup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import prompt_for  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_records(cfg, subset):
    data = ROOT / cfg["train_data"]
    expected = (ROOT / cfg["train_checksum"]).read_text().split()[0]
    actual = sha256_file(data)
    if actual != expected:
        sys.exit(f"{data} does not match {cfg['train_checksum']} ({actual} != {expected})")
    rows = [json.loads(l) for l in data.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = rows[: cfg["max_train_examples"]]
    return rows[:subset] if subset else rows


def encode(rows, tok, cfg):
    eos = tok.eos_token_id
    examples, truncated = [], 0
    for r in rows:
        p = tok(prompt_for(r["text"])).input_ids
        t = tok(" " + r["teacher_raw"]).input_ids + [eos]
        ids = p + t
        labels = ([-100] * len(p) if cfg["loss_on_reply_only"] else p) + t
        if len(ids) > cfg["max_seq_len"]:
            ids, labels, truncated = ids[: cfg["max_seq_len"]], labels[: cfg["max_seq_len"]], truncated + 1
        examples.append((ids, labels))
    return examples, truncated


def batches(examples, order, batch_size, pad_id):
    for i in range(0, len(order), batch_size):
        chunk = [examples[j] for j in order[i : i + batch_size]]
        width = max(len(ids) for ids, _ in chunk)
        ids = torch.full((len(chunk), width), pad_id, dtype=torch.long)
        lab = torch.full((len(chunk), width), -100, dtype=torch.long)
        att = torch.zeros((len(chunk), width), dtype=torch.long)
        for k, (a, b) in enumerate(chunk):
            ids[k, : len(a)], lab[k, : len(b)], att[k, : len(a)] = torch.tensor(a), torch.tensor(b), 1
        yield ids, lab, att


def write_tar(model_dir, version):
    """Deterministic archive of the model files (fixed order, times and owners)."""
    names = sorted(p.name for p in model_dir.iterdir()
                   if p.is_file() and not p.name.endswith((".tar", ".sha256")))
    tar_path = model_dir / f"model-{version}.tar"
    with tarfile.open(tar_path, "w", format=tarfile.USTAR_FORMAT) as tf:
        for n in names:
            data = (model_dir / n).read_bytes()
            info = tarfile.TarInfo(n)
            info.size, info.mtime, info.mode, info.uid, info.gid, info.uname, info.gname = len(data), 0, 0o644, 0, 0, "", ""
            tf.addfile(info, io.BytesIO(data))
    (model_dir / "files.sha256").write_text("".join(f"{sha256_file(model_dir / n)}  {n}\n" for n in names))
    # model.sha256 is the checksum of the archive: that is also what the GitHub Release asset must match.
    (model_dir / "model.sha256").write_text(f"{sha256_file(tar_path)}  {tar_path.name}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="training/config.yaml")
    ap.add_argument("--subset", type=int, default=0)
    args = ap.parse_args()
    cfg = yaml.safe_load((ROOT / args.config).read_text())

    for lib, want in cfg["libraries"].items():
        if lib == "python":
            continue
        have = pkg_version(lib)
        if have != want:
            print(f"warning: {lib} is {have}, config says {want}", file=sys.stderr)

    seed = cfg["seed"]
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    device = torch.device(cfg["device"])

    rows = load_records(cfg, args.subset)
    tok = AutoTokenizer.from_pretrained(cfg["model_name"])
    examples, truncated = encode(rows, tok, cfg)
    model = AutoModelForCausalLM.from_pretrained(cfg["model_name"], dtype=torch.float32).to(device)  # the hub checkpoint is float16, which is very slow on CPU
    model.train()
    print(f"{len(examples)} examples, {truncated} truncated, device {device}, version {cfg['version']}", flush=True)

    steps_per_epoch = -(-len(examples) // cfg["batch_size"])
    total = steps_per_epoch * cfg["epochs"]
    opt = torch.optim.AdamW(model.parameters(), lr=cfg["learning_rate"], weight_decay=cfg["weight_decay"])
    sched = get_linear_schedule_with_warmup(opt, int(cfg["warmup_ratio"] * total), total)

    if args.subset:
        out_root = ROOT / "out" / "subset-test"
        loss_csv = out_root / "loss.csv"
    else:
        out_root = ROOT / cfg["out_dir"]
        loss_csv = ROOT / cfg["loss_csv"]
    loss_csv.parent.mkdir(parents=True, exist_ok=True)

    rng = random.Random(seed)
    history = []
    for epoch in range(1, cfg["epochs"] + 1):
        order = list(range(len(examples)))
        rng.shuffle(order)
        t0, loss_sum, tok_sum = time.time(), 0.0, 0
        for ids, lab, att in batches(examples, order, cfg["batch_size"], tok.pad_token_id):
            out = model(input_ids=ids.to(device), attention_mask=att.to(device), labels=lab.to(device))
            out.loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            opt.zero_grad(set_to_none=True)
            n = int((lab[:, 1:] != -100).sum())
            loss_sum += out.loss.item() * n
            tok_sum += n
        history.append((epoch, loss_sum / tok_sum))
        print(f"epoch {epoch}/{cfg['epochs']}  loss {history[-1][1]:.4f}  ({time.time() - t0:.0f}s)", flush=True)

    with loss_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["epoch", "loss"])
        w.writerows((e, f"{l:.6f}") for e, l in history)

    model_dir = out_root / cfg["version"]
    model_dir.mkdir(parents=True, exist_ok=True)
    model.eval()
    model.save_pretrained(model_dir)
    tok.save_pretrained(model_dir)
    (model_dir / "version.json").write_text(json.dumps({
        "version": cfg["version"], "base_model": cfg["model_name"], "seed": seed, "epochs": cfg["epochs"],
        "learning_rate": cfg["learning_rate"], "batch_size": cfg["batch_size"], "examples": len(examples),
        "subset": args.subset or None, "train_data_sha256": sha256_file(ROOT / cfg["train_data"]),
        "final_loss": history[-1][1]}, indent=2) + "\n")
    write_tar(model_dir, cfg["version"])
    print("saved", model_dir.relative_to(ROOT))
    print((model_dir / "model.sha256").read_text().strip())


if __name__ == "__main__":
    main()

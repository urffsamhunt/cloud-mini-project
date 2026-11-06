"""Run a model on a labelled file and write predictions for tools/score.py.

Usage: python training/predict.py --model out/models/v1 --data data/validation.jsonl --out results/student_v1_predictions.jsonl
       python training/predict.py --model EleutherAI/pythia-70m ...      (the untrained base model)

The prompt is the same "Command: <text>\\nJSON:" the student was trained on. Decoding is greedy.
The prediction is the raw generated text up to the first newline (or end of sequence),
so the base model, which does not stop on its own, is judged on its first line only.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import prompt_for  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", default="data/validation.jsonl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-new-tokens", type=int, default=80)
    ap.add_argument("--batch-size", type=int, default=16)
    args = ap.parse_args()

    torch.manual_seed(0)
    tok = AutoTokenizer.from_pretrained(args.model, padding_side="left")
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(args.model, dtype=torch.float32).eval()

    rows = [json.loads(l) for l in Path(args.data).read_text(encoding="utf-8").splitlines() if l.strip()]
    out = []
    t0 = time.time()
    for i in range(0, len(rows), args.batch_size):
        chunk = rows[i : i + args.batch_size]
        enc = tok([prompt_for(r["text"]) for r in chunk], return_tensors="pt", padding=True)
        with torch.no_grad():
            gen = model.generate(**enc, max_new_tokens=args.max_new_tokens, do_sample=False,
                                 pad_token_id=tok.pad_token_id, eos_token_id=tok.eos_token_id)
        for r, g in zip(chunk, gen[:, enc.input_ids.shape[1]:]):
            text = tok.decode(g, skip_special_tokens=True)
            out.append({"id": r["id"], "prediction": text.split("\n")[0].strip()})
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in out), encoding="utf-8")
    print(f"{len(out)} predictions in {time.time() - t0:.0f}s -> {args.out}")


if __name__ == "__main__":
    main()

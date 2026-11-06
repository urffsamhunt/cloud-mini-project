"""Clean the teacher's replies and build the training set (Task 1, step 6).

Reads every shard (datasets/teacher/shard-*.jsonl), removes bad records, keeps the
rest in id order and writes train.jsonl plus its SHA-256 checksum.

Rejection rules, applied in this order (a record is counted under the FIRST rule it breaks):
  (a) the reply is not valid JSON
  (b) the reply's keys are not exactly intent, date, time, place
  (c) the intent is not one of the eight
  (d) a slot value is neither null nor text that appears in the command
Then, among the records that survived (a)-(d):
  (e) duplicate commands (exact same text): keep the one with the smallest id

Source and destination:
  S3_ENDPOINT set  -> read s3://datasets/teacher/, write s3://datasets/v1/{train.jsonl,train.sha256}
  otherwise        -> read --shards (default out/teacher), nothing is uploaded
The same files are always written under --out (default out/v1).
The output is deterministic: the same shards always give a byte-identical train.jsonl.
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_shards(args):
    """Return the raw lines of all shard files, as a list of (source name, line)."""
    if os.environ.get("S3_ENDPOINT"):
        import boto3
        s3 = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"])
        pages = s3.get_paginator("list_objects_v2").paginate(Bucket="datasets", Prefix="teacher/")
        keys = sorted(o["Key"] for p in pages for o in p.get("Contents", []) if o["Key"].endswith(".jsonl"))
        return [(k, s3.get_object(Bucket="datasets", Key=k)["Body"].read().decode("utf-8")) for k in keys]
    return [(p.name, p.read_text(encoding="utf-8")) for p in sorted(Path(args.shards).glob("shard-*.jsonl"))]


def classify(rec, schema):
    """Return the rejection reason letter for one shard record, or None if it is good."""
    try:
        obj = json.loads(rec["teacher_raw"])
    except (ValueError, TypeError):
        return "a"
    if not isinstance(obj, dict) or sorted(obj) != sorted(schema["keys"]):
        return "b"
    if not isinstance(obj["intent"], str) or obj["intent"] not in schema["intents"]:
        return "c"
    for slot in ("date", "time", "place"):
        v = obj[slot]
        if v is not None and not (isinstance(v, str) and v in rec["text"]):
            return "d"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", default="out/teacher")
    ap.add_argument("--out", default="out/v1")
    ap.add_argument("--schema", default=str(ROOT / "data" / "schema.json"))
    ap.add_argument("--report", default=str(ROOT / "results" / "clean_report.json"))
    args = ap.parse_args()

    schema = json.loads(Path(args.schema).read_text())
    shards = read_shards(args)
    if not shards:
        sys.exit("no shard files found")

    records = []
    for _, body in shards:
        records += [json.loads(l) for l in body.splitlines() if l.strip()]
    ids = [r["id"] for r in records]
    if len(ids) != len(set(ids)):
        sys.exit("an id appears in more than one shard output")
    records.sort(key=lambda r: r["id"])

    counts = {"input": len(records), "a_invalid_json": 0, "b_wrong_keys": 0, "c_bad_intent": 0,
              "d_slot_not_in_command": 0, "e_duplicates": 0, "kept": 0}
    names = {"a": "a_invalid_json", "b": "b_wrong_keys", "c": "c_bad_intent", "d": "d_slot_not_in_command"}
    rejected, survivors = [], []
    for r in records:
        why = classify(r, schema)
        if why:
            counts[names[why]] += 1
            rejected.append({"id": r["id"], "text": r["text"], "reason": names[why], "teacher_raw": r["teacher_raw"]})
        else:
            survivors.append(r)

    seen, kept = set(), []
    for r in survivors:                      # already in id order, so the first one seen has the smallest id
        if r["text"] in seen:
            counts["e_duplicates"] += 1
            rejected.append({"id": r["id"], "text": r["text"], "reason": "e_duplicates", "teacher_raw": r["teacher_raw"]})
        else:
            seen.add(r["text"])
            kept.append(r)
    counts["kept"] = len(kept)
    assert counts["input"] == sum(v for k, v in counts.items() if k != "input"), "counts do not add up"

    train = "".join(json.dumps({"id": r["id"], "text": r["text"], "teacher_raw": r["teacher_raw"]}, ensure_ascii=False) + "\n" for r in kept)
    digest = hashlib.sha256(train.encode("utf-8")).hexdigest()
    checksum_line = f"{digest}  train.jsonl\n"

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "train.jsonl").write_text(train, encoding="utf-8")
    (out / "train.sha256").write_text(checksum_line)
    (out / "rejected.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rejected), encoding="utf-8")

    report = {"shard_files": [n for n, _ in shards], "counts": counts, "sha256": digest}
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")

    if os.environ.get("S3_ENDPOINT"):
        import boto3
        s3 = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"])
        s3.put_object(Bucket="datasets", Key="v1/train.jsonl", Body=train.encode("utf-8"))
        s3.put_object(Bucket="datasets", Key="v1/train.sha256", Body=checksum_line.encode())
        print("uploaded s3://datasets/v1/train.jsonl and train.sha256")

    for k, v in counts.items():
        print(f"{k:24s}{v:6d}")
    print("sha256", digest)


if __name__ == "__main__":
    main()

"""Upload a trained model directory to object storage as models/<version>/ and verify it.

Usage (needs S3_ENDPOINT and credentials in the environment; scripts/with_s3.sh sets them):
  python training/upload_model.py out/models/v1 v1
Uploads every file in the directory (model, tokenizer, version.json, checksums, archive), then
downloads the archive again and checks that its SHA-256 matches model.sha256.
"""
import hashlib
import os
import sys
from pathlib import Path

import boto3


def main():
    src, version = Path(sys.argv[1]), sys.argv[2]
    s3 = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"])
    for p in sorted(src.iterdir()):
        if p.is_file():
            s3.upload_file(str(p), "models", f"{version}/{p.name}")
            print(f"uploaded models/{version}/{p.name}  ({p.stat().st_size} bytes)")
    want, name = (src / "model.sha256").read_text().split()
    h = hashlib.sha256()
    body = s3.get_object(Bucket="models", Key=f"{version}/{name}")["Body"]
    for chunk in iter(lambda: body.read(1 << 20), b""):
        h.update(chunk)
    ok = h.hexdigest() == want
    print(("checksum OK  " if ok else "CHECKSUM MISMATCH  ") + want)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

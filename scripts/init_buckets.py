"""Create the buckets `datasets` and `models` in SeaweedFS and upload the command pool.

Credentials come from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in the environment.
Usage: python scripts/init_buckets.py [--endpoint http://localhost:8333]
"""
import argparse
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://localhost:8333")
    ap.add_argument("--pool", default=str(ROOT / "data" / "commands_pool.jsonl"))
    a = ap.parse_args()

    s3 = boto3.client("s3", endpoint_url=a.endpoint)
    for bucket in ("datasets", "models"):
        try:
            s3.create_bucket(Bucket=bucket)
            print("created bucket", bucket)
        except ClientError as e:
            if e.response["Error"]["Code"] in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                print("bucket exists", bucket)
            else:
                raise
    s3.upload_file(a.pool, "datasets", "commands_pool.jsonl")
    print("uploaded commands_pool.jsonl ->", "datasets/commands_pool.jsonl")
    for b in s3.list_buckets()["Buckets"]:
        print("bucket:", b["Name"])
    for o in s3.list_objects_v2(Bucket="datasets").get("Contents", []):
        print("  datasets/%s  %d bytes" % (o["Key"], o["Size"]))


if __name__ == "__main__":
    main()

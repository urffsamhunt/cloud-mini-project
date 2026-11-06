#!/usr/bin/env bash
# Run a command with S3 access to SeaweedFS: port-forwards the S3 port, exports the
# endpoint and credentials (read from the Kubernetes Secret), runs the command, cleans up.
# Usage: scripts/with_s3.sh <command> [args...]
set -euo pipefail
cd "$(dirname "$0")/.."

kubectl -n data port-forward svc/seaweedfs 8333:8333 >/dev/null 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do
  (echo > /dev/tcp/127.0.0.1/8333) 2>/dev/null && break
  sleep 1
done

secret() { kubectl -n pipeline get secret s3-creds -o "jsonpath={.data.$1}" | base64 -d; }
export AWS_ACCESS_KEY_ID="$(secret AWS_ACCESS_KEY_ID)"
export AWS_SECRET_ACCESS_KEY="$(secret AWS_SECRET_ACCESS_KEY)"
export AWS_DEFAULT_REGION=us-east-1
export S3_ENDPOINT=http://localhost:8333
"$@"

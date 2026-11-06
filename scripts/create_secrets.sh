#!/usr/bin/env bash
# Create the S3 credentials as Kubernetes Secrets, with random keys generated now.
# Nothing is written into the repository. Safe to re-run: existing secrets are kept.
set -euo pipefail

if kubectl -n data get secret seaweedfs-s3 >/dev/null 2>&1; then
  echo "secrets already exist, keeping them"
  exit 0
fi

ACCESS_KEY="$(openssl rand -hex 10)"
SECRET_KEY="$(openssl rand -hex 20)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cat > "$TMP/s3.json" <<JSON
{"identities":[{"name":"admin","credentials":[{"accessKey":"$ACCESS_KEY","secretKey":"$SECRET_KEY"}],"actions":["Admin","Read","Write","List","Tagging"]}]}
JSON

kubectl -n data create secret generic seaweedfs-s3 --from-file=s3.json="$TMP/s3.json"
for ns in pipeline app; do
  kubectl -n "$ns" create secret generic s3-creds \
    --from-literal=AWS_ACCESS_KEY_ID="$ACCESS_KEY" \
    --from-literal=AWS_SECRET_ACCESS_KEY="$SECRET_KEY" \
    --from-literal=AWS_DEFAULT_REGION=us-east-1
done
echo "created secrets seaweedfs-s3 (data) and s3-creds (pipeline, app)"

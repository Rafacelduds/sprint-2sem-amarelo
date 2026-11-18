#!/usr/bin/env bash
set -euo pipefail

awslocal s3 mb "s3://${S3_BUCKET:-raw-data}" 2>/dev/null || true
awslocal s3api put-bucket-versioning --bucket "${S3_BUCKET:-raw-data}" \
  --versioning-configuration Status=Enabled


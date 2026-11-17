#!/usr/bin/env bash
set -euo pipefail

awslocal s3 mb "s3://${S3_BUCKET:-raw-data}" 2>/dev/null || true


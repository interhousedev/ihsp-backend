#!/usr/bin/env bash
# Build the backend image used by every process.
set -euo pipefail
cd "$(dirname "$0")/.."
docker build -t ihsp-backend:dev .

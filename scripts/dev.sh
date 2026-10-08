#!/usr/bin/env bash
# Run one backend process against the development compose stack.
# Usage: scripts/dev.sh <all|identity|api|bot|mail|worker|scheduler|migrate|seed-demo|...>
set -euo pipefail
cd "$(dirname "$0")/.."

process="${1:?usage: scripts/dev.sh <process> [args...]}"
shift

set -a
# shellcheck disable=SC1091
source materials/dev.env
set +a
export IHSP_ENV_FILE=materials/dev.env

docker compose -f materials/docker-compose.dev.yaml up -d --wait

key=materials/dev-keys/jwt-bearer.pem
if [ ! -f "$key" ]; then
    mkdir -p materials/dev-keys
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$key"
    chmod 600 "$key"
fi

uv run python -m app migrate
# Idempotent: OAuth clients and the JWT-bearer trust in Hydra.
uv run python scripts/hydra_bootstrap.py
exec uv run python -m app "$process" "$@"

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
# Local secrets such as the OpenRouter key: git-ignored, optional.
if [ -f materials/dev-keys/secrets.env ]; then
    # shellcheck disable=SC1091
    source materials/dev-keys/secrets.env
fi
set +a
export IHSP_ENV_FILE=materials/dev.env,?materials/dev-keys/secrets.env

docker compose -f materials/docker-compose.dev.yaml up -d --wait

key=materials/dev-keys/jwt-bearer.pem
if [ ! -f "$key" ]; then
    mkdir -p materials/dev-keys
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$key"
    chmod 600 "$key"
fi

# Web Push: a throw-away VAPID pair for this checkout (git-ignored); push is off without it.
vapid=materials/dev-keys/vapid.env
uv run python scripts/gen_vapid.py --out "$vapid"
set -a
# shellcheck disable=SC1090
source "$vapid"
set +a

uv run python -m app migrate
# Idempotent: OAuth clients and the JWT-bearer trust in Hydra.
uv run python scripts/hydra_bootstrap.py
exec uv run python -m app "$process" "$@"

#!/usr/bin/env bash
# Run the admission stack on the host: api, worker, bot and the web dev servers
# for id, admission, admin and share, with real AI keys from the git-ignored
# materials/dev-keys/secrets.env (never printed).
# Usage: scripts/admission_local.sh   (Ctrl-C stops everything)
# Env: IHSP_WEB_DIR (default ../iht-web), AI_MODE (real|fake; default real when a key exists).
set -euo pipefail
cd "$(dirname "$0")/.."
backend_dir=$(pwd)
web_dir=$(cd "${IHSP_WEB_DIR:-../iht-web}" && pwd)

secrets=materials/dev-keys/secrets.env
set -a
# shellcheck disable=SC1091
source materials/dev.env
if [ -f "$secrets" ]; then
    # shellcheck disable=SC1090
    source "$secrets"
else
    echo "warning: $secrets missing; AI stays in fake mode" >&2
fi
set +a
export IHSP_ENV_FILE=materials/dev.env,?materials/dev-keys/secrets.env

# Real AI only when a key is present; the values are never echoed.
if [ -n "${IHSP_OPENROUTER__API_KEY:-}" ] && [ "${AI_MODE:-real}" = real ]; then
    export IHSP_OPENROUTER__MODE=real
    [ -n "${IHSP_EXA__API_KEY:-}" ] && export IHSP_EXA__MODE=real
    echo "AI: real (OpenRouter key loaded)"
else
    export IHSP_OPENROUTER__MODE=fake
    echo "AI: fake"
fi

# The apps reach each other on these origins (same values as materials/dev.env).
export IHSP_URLS__ID=http://localhost:3001
export IHSP_URLS__ADMIN=http://localhost:3004
export IHSP_URLS__SHARE=http://localhost:3006
export IHSP_URLS__ADMISSION=http://localhost:3009
export IHSP_ADMISSION__ENABLED=true

docker compose -f materials/docker-compose.dev.yaml up -d --wait

key=materials/dev-keys/jwt-bearer.pem
if [ ! -f "$key" ]; then
    mkdir -p materials/dev-keys
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$key"
    chmod 600 "$key"
fi
uv run python scripts/gen_vapid.py --out materials/dev-keys/vapid.env
set -a
# shellcheck disable=SC1091
source materials/dev-keys/vapid.env
set +a

# Once, not per process: migrations and the Hydra clients (includes `admission`).
uv run python -m app migrate
uv run python scripts/hydra_bootstrap.py

mkdir -p .local-logs
pids=()
cleanup() {
    trap - INT TERM EXIT
    for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
    wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

run() { # name, dir, command...
    local name=$1 dir=$2
    shift 2
    (cd "$dir" && exec "$@") >".local-logs/$name.log" 2>&1 &
    pids+=("$!")
}

# `all` serves identity (/v1/id, /v1/oauth) and the API on :8000; `api` alone has no sign-in.
for proc in all worker bot; do
    run "$proc" "$backend_dir" uv run python -m app "$proc"
done
for app in id admission admin share; do
    run "web-$app" "$web_dir/apps/$app" bun run dev
done

cat <<'URLS'
api        http://localhost:8000   (docs: /docs)
id         http://localhost:3001
admission  http://localhost:3009
admin      http://localhost:3004
share      http://localhost:3006/ai   guest viewer: http://localhost:3006/ai/admission-guest/#<token>
Logs: .local-logs/<name>.log. Ctrl-C stops all.
URLS
wait

#!/usr/bin/env bash
# Stop the local full stack (project `ihsp-local`).
#
# Usage: scripts/local_down.sh [--wipe]
#   --wipe   also delete the volumes: database, Redis, uploaded files and the dev Vault
#            data are gone; the next local_up.sh starts from scratch.
set -euo pipefail
cd "$(dirname "$0")/.."

wipe=()
for arg in "$@"; do
    case "$arg" in
        --wipe) wipe=(--volumes) ;;
        -h | --help)
            sed -n '2,7p' "$0"
            exit 0
            ;;
        *)
            echo "unknown argument: $arg" >&2
            exit 2
            ;;
    esac
done

args=(-f materials/docker-compose.local.yaml)
if [ -f .env.local ]; then
    args=(--env-file .env.local "${args[@]}")
fi

# `--profile tools` so that one-off containers of the tools profile are removed as well.
docker compose "${args[@]}" --profile tools down --remove-orphans "${wipe[@]}"

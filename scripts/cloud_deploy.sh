#!/usr/bin/env bash
# Deploy the production stack to a server over SSH (run it from your machine).
#
# Usage: scripts/cloud_deploy.sh <ssh-host> [--init] [--push-env] [--no-pull] [--tag TAG]
#   <ssh-host>   anything `ssh` accepts: deploy@203.0.113.7, a Host from ~/.ssh/config
#   --init       first deployment: after copying the files run scripts/prod_init.sh on the
#                server (secrets, Vault, certificates, Hydra, first administrator)
#   --push-env   overwrite the server's .env.prod with the local backend/.env.prod
#                (by default an existing server copy is kept: it holds the Vault AppRole ids)
#   --no-pull    do not pull images (they are already on the server)
#   --tag TAG    set TAG in the server's .env.prod first (1.2.0, sha-<40 hex>, latest); a
#                rollback is the same command with the previous tag
#
# On the server (IHSP_REMOTE_DIR, default /opt/ihsp) the layout is:
#   materials/ scripts/ secrets/ data/ backups/ .env.prod
# Prerequisites there: Docker with the compose plugin, the SSH user in the `docker` group
# and owner of the directory (sudo mkdir -p /opt/ihsp && sudo chown $USER /opt/ihsp), and
# `docker login ghcr.io` if the images are private.
set -euo pipefail
cd "$(dirname "$0")/.."

host=
init=0
push_env=0
pull=1
tag=
while [ $# -gt 0 ]; do
    case "$1" in
        --init) init=1; shift ;;
        --push-env) push_env=1; shift ;;
        --no-pull) pull=0; shift ;;
        --tag) tag=${2:?--tag needs a value}; shift 2 ;;
        -h | --help) sed -n '2,19p' "$0"; exit 0 ;;
        -*) echo "unknown argument: $1" >&2; exit 2 ;;
        *) host=$1; shift ;;
    esac
done
[ -n "$host" ] || { echo "usage: scripts/cloud_deploy.sh <ssh-host> [--init] [--push-env] [--no-pull] [--tag TAG]" >&2; exit 2; }

dir=${IHSP_REMOTE_DIR:-/opt/ihsp}
say() { printf '==> %s\n' "$*"; }

say "copying files to $host:$dir"
ssh "$host" "mkdir -p '$dir/materials' '$dir/scripts' '$dir/secrets' '$dir/data' '$dir/backups' && chmod 700 '$dir/secrets' '$dir/data' '$dir/backups'"
rsync -az --delete \
    --exclude 'dev-keys' --exclude '__pycache__' \
    materials/ "$host:$dir/materials/"
rsync -az \
    --include 'prod_init.sh' --include 'backup.sh' --include 'restore.sh' \
    --include 'hydra_bootstrap.py' --exclude '*' \
    scripts/ "$host:$dir/scripts/"

if [ -d secrets ]; then
    rsync -az --ignore-existing secrets/ "$host:$dir/secrets/"
fi

if [ "$push_env" -eq 1 ] || ! ssh "$host" "test -f '$dir/.env.prod'"; then
    if [ -f .env.prod ]; then
        say "copying .env.prod"
        scp -q .env.prod "$host:$dir/.env.prod"
        ssh "$host" "chmod 600 '$dir/.env.prod'"
    elif [ "$init" -eq 0 ]; then
        echo "no .env.prod here or on the server: run scripts/cloud_deploy.sh $host --init" >&2
        exit 1
    fi
fi

case "$tag" in
    "" | *[!A-Za-z0-9._-]*) [ -z "$tag" ] || { echo "invalid tag: $tag" >&2; exit 2; } ;;
esac
if [ -n "$tag" ] && [ "$init" -eq 0 ]; then
    say "setting TAG=$tag in $dir/.env.prod"
    ssh "$host" "cd '$dir' && sed -i.bak 's/^TAG=.*/TAG=$tag/' .env.prod && rm -f .env.prod.bak && chmod 600 .env.prod"
fi

if [ "$init" -eq 1 ]; then
    say "first-time setup on the server (interactive)"
    ssh -t "$host" "cd '$dir' && chmod +x scripts/*.sh && scripts/prod_init.sh env" || true
    echo
    echo "If .env.prod on the server still has CHANGE_ME values, edit it there now ($dir/.env.prod),"
    read -r -p "then press Enter to continue (Ctrl-C to stop): " _
    ssh -t "$host" "cd '$dir' && scripts/prod_init.sh init"
    exit 0
fi

say "deploying"
# shellcheck disable=SC2087
ssh "$host" "cd '$dir' && PULL=$pull bash -s" << 'REMOTE'
set -euo pipefail
dc() { docker compose --env-file .env.prod -f materials/docker-compose.prod.yaml "$@"; }
domain=$(sed -n 's/^DOMAIN=//p' .env.prod | tail -n 1)

if [ "$PULL" = "1" ]; then
    dc pull --ignore-buildable
fi

# Data stores first, then the one-shot migrations, so a failed migration stops the
# deployment before any application container is replaced.
dc up -d --wait postgres redis vault
sealed=$(dc exec -T vault vault status 2> /dev/null | awk '$1 == "Sealed" { print $2 }' || true)
if [ "$sealed" != "false" ]; then
    echo "WARNING: Vault is sealed. Registration and EMIS sync pause until: scripts/prod_init.sh unseal" >&2
fi
dc run --rm --no-deps hydra-migrate
dc run --rm --no-deps migrate

dc up -d --wait --remove-orphans

dc ps
if command -v curl > /dev/null; then
    curl -fsS --max-time 10 "https://api.$domain/health" && echo
    curl -fsS --max-time 10 "https://id.$domain/.well-known/openid-configuration" > /dev/null && echo "hydra discovery ok"
fi
REMOTE
say "deployed"

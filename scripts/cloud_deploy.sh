#!/usr/bin/env bash
# Deploy the production stack to a server over SSH (run it from your machine).
#
# Usage: scripts/cloud_deploy.sh <ssh-host> [--init] [--push-env] [--no-pull] [--tag TAG]
# (scripts/deploy.sh wraps this with deploy.local.env, a plan and a confirmation.)
# A deploy takes a pre-migration pg_dump (backups/pre-<tag>-<ts>.sql.gz), runs the
# migrations, starts the services and watches them for IHSP_DEPLOY_STABLE_SECS (60); if they
# restart or /health fails, the previous TAG is redeployed (the database is not restored).
#   <ssh-host>   anything `ssh` accepts: deploy@203.0.113.7, a Host from ~/.ssh/config
#   --init       first deployment: after copying the files run scripts/prod_init.sh on the
#                server (secrets, Vault, certificates, Hydra, first administrator)
#   --push-env   overwrite the server's .env.prod with the local .env.prod
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
        -h | --help) sed -n '2,24p' "$0"; exit 0 ;;
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
set_tag() {
    [ -n "$tag" ] || return 0
    say "setting TAG=$tag in $dir/.env.prod"
    ssh "$host" "cd '$dir' && test -f .env.prod && sed -i.bak 's/^TAG=.*/TAG=$tag/' .env.prod && rm -f .env.prod.bak && chmod 600 .env.prod"
}
# The tag now in .env.prod is the rollback target if this release fails.
prev_tag=$(ssh "$host" "sed -n 's/^TAG=//p' '$dir/.env.prod' 2> /dev/null | tail -n 1" || true)
[ "$init" -eq 1 ] || set_tag

if [ "$init" -eq 1 ]; then
    say "first-time setup on the server (interactive)"
    ssh -t "$host" "cd '$dir' && chmod +x scripts/*.sh && scripts/prod_init.sh env" || true
    echo
    echo "If .env.prod on the server still has CHANGE_ME values, edit it there now ($dir/.env.prod),"
    read -r -p "then press Enter to continue (Ctrl-C to stop): " _
    # The first setup pulls the images of TAG: --tag applies to it too.
    set_tag
    ssh -t "$host" "cd '$dir' && scripts/prod_init.sh init"
    exit 0
fi

say "deploying"
# The script is uploaded, not piped to `bash -s`: then stdin is the script itself, a
# `docker compose run` reads the rest of it, and the deploy ends with success before `up`.
ssh "$host" "cat > '$dir/.deploy.sh'" << 'REMOTE'
set -euo pipefail
dc() { docker compose --env-file .env.prod -f materials/docker-compose.prod.yaml "$@"; }
domain=$(sed -n 's/^DOMAIN=//p' .env.prod | tail -n 1)
tag=$(sed -n 's/^TAG=//p' .env.prod | tail -n 1)
prev_tag=${PREV_TAG:-$tag}
phase=init
predump=
echo "==> deploying TAG=$tag (previous: $prev_tag)"
set_env_tag() { sed -i.bak "s/^TAG=.*/TAG=$1/" .env.prod && rm -f .env.prod.bak && chmod 600 .env.prod; }
# On any failure show why: the state of every service and the last log lines of the ones
# that are not running (a backend that refuses its settings exits at once). Then undo:
#   phase init/pre  nothing was replaced (the migration runs first): restore the previous TAG.
#   phase post      migrations are applied: redeploy the previous TAG (rollback).
# The database is never restored automatically; migrations are forward only.
on_error() {
    trap - ERR
    echo "DEPLOY FAILED (phase: $phase). Services:" >&2
    dc ps -a >&2 || true
    for svc in migrate api worker identity bot mail scheduler web; do
        echo "--- $svc (last 30 lines)" >&2
        dc logs --no-color --tail 30 "$svc" >&2 2> /dev/null || true
    done
    set_env_tag "$prev_tag" || true
    if [ "$phase" = "post" ]; then
        echo "ROLLBACK: redeploying TAG=$prev_tag" >&2
        if dc pull --ignore-buildable >&2 && dc up -d --wait --force-recreate >&2; then
            echo "ROLLBACK done: containers run TAG=$prev_tag." >&2
        else
            echo "ROLLBACK FAILED: fix by hand (TAG=$prev_tag is set in .env.prod)." >&2
        fi
        echo "Migrations are forward-only and stay applied; the previous schema is NOT restored." >&2
        [ -z "$predump" ] || echo "Pre-deploy database dump for a manual restore: $PWD/$predump" >&2
    else
        echo "Nothing was replaced; TAG restored to $prev_tag." >&2
    fi
    exit 1
}
trap on_error ERR

if [ "$PULL" = "1" ]; then
    dc pull --ignore-buildable
fi

# Data stores first, then the one-shot migrations, so a failed migration stops the
# deployment before any application container is replaced.
dc up -d --wait postgres redis vault
# Bugsink's database (BUGSINK_DB_MODE in .env.prod): `main` (default) keeps it in the main
# PostgreSQL; the role and database are created here if missing and the role's password is set
# from BUGSINK_DB_PASSWORD on every deploy (idempotent). `dedicated` starts the bugsink-db
# container (profile bugsink-dedicated) instead. The shell variables below win over .env.prod.
bugsink_mode=$(sed -n 's/^BUGSINK_DB_MODE=//p' .env.prod | tail -n 1)
case "${bugsink_mode:-main}" in
    main)
        export BUGSINK_DB_HOST=postgres
        bugsink_pw=$(sed -n 's/^BUGSINK_DB_PASSWORD=//p' .env.prod | tail -n 1)
        [ -n "$bugsink_pw" ] || { echo "BUGSINK_DB_PASSWORD is not set in .env.prod" >&2; exit 1; }
        # `-e BUGSINK_PW` (no value) copies the variable from this shell, so the password
        # never appears in the docker argv (ps); it is unset right after the command.
        export BUGSINK_PW="$bugsink_pw"
        dc exec -T -e BUGSINK_PW postgres sh -c \
            'psql -v ON_ERROR_STOP=1 -U ihsp -d postgres -v pw="$BUGSINK_PW"' << 'SQL'
SELECT format('CREATE ROLE bugsink LOGIN PASSWORD %L', :'pw') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bugsink') \gexec
SELECT format('ALTER ROLE bugsink LOGIN PASSWORD %L', :'pw') \gexec
SELECT 'CREATE DATABASE bugsink OWNER bugsink' WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'bugsink') \gexec
SQL
        unset BUGSINK_PW
        ;;
    dedicated)
        export BUGSINK_DB_HOST=bugsink-db COMPOSE_PROFILES=bugsink-dedicated
        dc up -d --wait bugsink-db
        ;;
    *) echo "BUGSINK_DB_MODE must be main or dedicated" >&2; exit 1 ;;
esac
sealed=$(dc exec -T vault vault status 2> /dev/null | awk '$1 == "Sealed" { print $2 }' || true)
if [ "$sealed" != "false" ]; then
    echo "WARNING: Vault is sealed. Registration and EMIS sync pause until: scripts/prod_init.sh unseal" >&2
fi
# --- point of no return for the schema: take a dump first (forward-only migrations).
phase=pre
stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p backups && chmod 700 backups
predump="backups/pre-${tag}-${stamp}.sql.gz"
echo "==> pre-migration dump: $predump"
dc exec -T postgres pg_dump -U ihsp -d ihsp | gzip > "$predump"
[ -s "$predump" ] || { echo "pre-migration dump is empty" >&2; exit 1; }
chmod 600 "$predump"

dc run --rm --no-deps hydra-migrate
# The migration runs the new image first: a bad .env.prod (for example an S3 endpoint
# with a path) stops here, before any running container is touched.
dc run --rm --no-deps migrate

# Migrations are applied: from here a failure rolls the containers back to PREV_TAG.
phase=post
# Services whose restart counters and health the stability gate watches.
gate_services="api worker identity bot mail scheduler web nginx"
dc up -d --wait --remove-orphans --force-recreate

stable_gate() {
    local secs=${IHSP_DEPLOY_STABLE_SECS:-60} svc id state base now deadline
    declare -A ids=() restarts=()
    for svc in $gate_services; do
        id=$(dc ps -q "$svc" 2> /dev/null | head -n 1 || true)
        [ -n "$id" ] || continue
        ids[$svc]=$id
        restarts[$svc]=$(docker inspect -f '{{.RestartCount}}' "$id")
    done
    echo "==> stability gate: ${secs}s, services: ${!ids[*]}"
    deadline=$((SECONDS + secs))
    while :; do
        for svc in "${!ids[@]}"; do
            state=$(docker inspect -f '{{.State.Running}} {{.State.Restarting}} {{.RestartCount}}' "${ids[$svc]}") || return 1
            base=${restarts[$svc]}
            if [ "$state" != "true false $base" ]; then
                echo "gate: $svc is unstable (running/restarting/count: $state, was count $base)" >&2
                return 1
            fi
        done
        if command -v curl > /dev/null; then
            curl -fsS --max-time 10 -o /dev/null "https://api.$domain/health" \
                || { echo "gate: https://api.$domain/health failed" >&2; return 1; }
        fi
        now=$SECONDS
        [ "$now" -lt "$deadline" ] || break
        sleep 5
    done
    echo "==> stable"
}
stable_gate

# Pre-created MCP clients get new fixed redirect URIs; idempotent, and a failure here
# must not fail a deploy whose containers are already up.
dc --profile tools run --rm --no-deps -T bootstrap python /scripts/hydra_bootstrap.py --mcp-clients-only \
    || echo "WARNING: MCP client redirect sync failed; rerun it after checking Hydra" >&2
# Containers that an interrupted earlier deploy renamed to <id>_ihsp-... are left over.
# grep finds nothing on a clean server, which must not fail the deploy (pipefail).
docker ps -a --format '{{.Names}}' | { grep -E '^[0-9a-f]{12}_ihsp-' || true; } | xargs -r docker rm -f
# The edge config is bind-mounted: a running nginx keeps the old upstreams until it reloads.
dc exec -T nginx nginx -s reload

dc ps
if command -v curl > /dev/null; then
    curl -fsS --max-time 10 "https://api.$domain/health" && echo
    curl -fsS --max-time 10 "https://id.$domain/.well-known/openid-configuration" > /dev/null && echo "hydra discovery ok"
fi
trap - ERR
echo "==> remote deploy finished"
REMOTE
ssh "$host" "cd '$dir' && PREV_TAG='$prev_tag' PULL=$pull IHSP_DEPLOY_STABLE_SECS='${IHSP_DEPLOY_STABLE_SECS:-60}' bash .deploy.sh < /dev/null; status=\$?; rm -f .deploy.sh; exit \$status"
say "deployed"

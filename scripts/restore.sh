#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh. DESTRUCTIVE: replaces the current data.
#
# Usage: scripts/restore.sh <backup-dir> [--with-redis] [--with-vault] [--yes]
#   --with-redis   also replace Redis (queues, rate limits; usually not needed)
#   --with-vault   also restore the Vault Raft snapshot. Needs a root token in VAULT_TOKEN
#                  and an unsealed Vault; the snapshot is only readable with the unseal
#                  keys that were current when it was taken.
#   --yes          do not ask for confirmation
#
# The application processes are stopped, PostgreSQL databases ihsp and hydra are restored
# with pg_restore --clean, then the stack is started again.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

ENV_FILE=.env.prod
COMPOSE_FILE=materials/docker-compose.prod.yaml
src=
with_redis=0
with_vault=0
assume_yes=0

while [ $# -gt 0 ]; do
    case "$1" in
        --with-redis) with_redis=1; shift ;;
        --with-vault) with_vault=1; shift ;;
        --yes) assume_yes=1; shift ;;
        -h | --help) sed -n '2,15p' "$0"; exit 0 ;;
        -*) echo "unknown argument: $1" >&2; exit 2 ;;
        *) src=$1; shift ;;
    esac
done

[ -n "$src" ] || { echo "usage: scripts/restore.sh <backup-dir> [--with-redis] [--with-vault] [--yes]" >&2; exit 2; }
[ -d "$src" ] || { echo "$src is not a directory" >&2; exit 1; }
src=$(cd "$src" && pwd)
[ -f "$src/ihsp.dump" ] && [ -f "$src/hydra.dump" ] || { echo "$src has no ihsp.dump / hydra.dump" >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "$ENV_FILE not found in $ROOT" >&2; exit 1; }

dc() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }
say() { printf '==> %s\n' "$*"; }

if [ -f "$src/SHA256SUMS" ]; then
    say "verifying checksums"
    (
        cd "$src"
        if command -v sha256sum > /dev/null; then
            sha256sum -c SHA256SUMS > /dev/null
        else
            shasum -a 256 -c SHA256SUMS > /dev/null
        fi
    )
fi

if [ "$assume_yes" -ne 1 ]; then
    read -r -p "Replace the databases of this server with $src? [type 'restore'] " answer
    [ "$answer" = "restore" ] || { echo "aborted"; exit 1; }
fi

say "stopping the application processes"
dc stop identity api bot mail worker scheduler hydra hydra-janitor

say "starting PostgreSQL"
dc up -d --wait postgres

# Objects keep their original owners (ihsp, hydra), so no --no-owner.
say "restoring ihsp"
dc exec -T postgres pg_restore -U ihsp -d ihsp --clean --if-exists --exit-on-error < "$src/ihsp.dump"
say "restoring hydra"
dc exec -T postgres pg_restore -U ihsp -d hydra --clean --if-exists --exit-on-error < "$src/hydra.dump"

if [ "$with_redis" -eq 1 ]; then
    [ -f "$src/redis.rdb" ] || { echo "$src/redis.rdb is missing" >&2; exit 1; }
    say "restoring Redis"
    dc stop redis
    # With appendonly yes Redis ignores dump.rdb at start. Load it in a throwaway server with
    # AOF off, switch AOF on (Redis rewrites it from memory), then start the real one.
    dc run --rm --no-deps -T -v "$src:/restore:ro" --entrypoint sh redis -c '
        set -e
        rm -rf /data/appendonlydir /data/dump.rdb
        cp /restore/redis.rdb /data/dump.rdb
        redis-server --appendonly no --daemonize yes --requirepass "$REDIS_PASSWORD" > /dev/null
        for i in $(seq 1 30); do redis-cli ping > /dev/null 2>&1 && break; sleep 1; done
        redis-cli CONFIG SET appendonly yes > /dev/null
        for i in $(seq 1 60); do
            redis-cli INFO persistence | grep -q "aof_rewrite_in_progress:0" && break
            sleep 1
        done
        redis-cli SHUTDOWN NOSAVE || true'
    dc up -d --wait redis
fi

if [ "$with_vault" -eq 1 ]; then
    [ -f "$src/vault.snap" ] || { echo "$src/vault.snap is missing" >&2; exit 1; }
    : "${VAULT_TOKEN:?export VAULT_TOKEN=<root token> to restore Vault}"
    say "restoring the Vault snapshot"
    dc up -d --wait vault
    # Not `compose cp`: it creates the file as root and the vault user could not read it.
    snap=$(dc exec -T vault sh -c 'f=$(mktemp /tmp/vault-restore.XXXXXX) && cat > "$f" && echo "$f"' \
        < "$src/vault.snap")
    dc exec -T -e VAULT_TOKEN vault vault operator raft snapshot restore -force "$snap"
    dc exec -T vault rm -f "$snap"
    echo "Vault may be sealed again after the restore: scripts/prod_init.sh unseal"
fi

say "starting the stack"
dc up -d --wait
echo "restore finished"

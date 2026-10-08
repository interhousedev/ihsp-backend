#!/usr/bin/env bash
# Back up a production server: PostgreSQL (databases ihsp and hydra), Redis and Vault.
# Run it on the server, in the deploy directory (cron line: see `prod_init.sh certs`).
#
# Usage: scripts/backup.sh [--dir DIR] [--keep N]
#   --dir DIR   where to write (default: ./backups)
#   --keep N    afterwards delete all but the N newest backups (default: keep everything)
#
# Output: DIR/<UTC timestamp>/{ihsp.dump,hydra.dump,redis.rdb,vault.snap,SHA256SUMS}
#   ihsp.dump, hydra.dump   pg_dump custom format (pg_restore)
#   redis.rdb               BGSAVE snapshot (rate limits, queues; optional to restore)
#   vault.snap              Raft snapshot, taken with the `backup` AppRole of .env.prod
# What is NOT in a backup, keep it somewhere safe yourself: .env.prod, secrets/ (JWT keys),
# the Vault unseal keys, and the S3 bucket (the cloud provider's durability covers it;
# student files are temporary by design).
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

ENV_FILE=.env.prod
COMPOSE_FILE=materials/docker-compose.prod.yaml
dir=backups
keep=0

while [ $# -gt 0 ]; do
    case "$1" in
        --dir) dir=${2:?--dir needs a value}; shift 2 ;;
        --keep) keep=${2:?--keep needs a value}; shift 2 ;;
        -h | --help) sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

[ -f "$ENV_FILE" ] || { echo "$ENV_FILE not found in $ROOT" >&2; exit 1; }
dc() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }
get_env() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1; }
say() { printf '==> %s\n' "$*"; }

stamp=$(date -u +%Y%m%dT%H%M%SZ)
out="$dir/$stamp"
mkdir -p "$out"
chmod 700 "$dir" "$out"
status=0

say "PostgreSQL: ihsp"
dc exec -T postgres pg_dump -U ihsp -Fc ihsp > "$out/ihsp.dump"
say "PostgreSQL: hydra"
dc exec -T postgres pg_dump -U ihsp -Fc hydra > "$out/hydra.dump"

say "Redis"
last=$(dc exec -T redis redis-cli LASTSAVE | tr -d '\r')
dc exec -T redis redis-cli BGSAVE > /dev/null
for _ in $(seq 1 60); do
    now=$(dc exec -T redis redis-cli LASTSAVE | tr -d '\r')
    [ "$now" != "$last" ] && break
    sleep 1
done
if [ "$now" = "$last" ]; then
    echo "warning: Redis BGSAVE did not finish in 60 s; no Redis copy" >&2
    status=1
else
    dc cp redis:/data/dump.rdb "$out/redis.rdb"
fi

say "Vault (Raft snapshot)"
role=$(get_env VAULT_BACKUP_ROLE_ID)
secret=$(get_env VAULT_BACKUP_SECRET_ID)
sealed=$(dc exec -T vault vault status 2> /dev/null | awk '$1 == "Sealed" { print $2 }' || true)
if [ -z "$role" ] || [ -z "$secret" ]; then
    echo "warning: no VAULT_BACKUP_ROLE_ID/SECRET_ID in $ENV_FILE (run scripts/prod_init.sh vault); no Vault copy" >&2
    status=1
elif [ "$sealed" != "false" ]; then
    echo "warning: Vault is sealed; no Vault copy (scripts/prod_init.sh unseal)" >&2
    status=1
else
    VAULT_BACKUP_ROLE_ID=$role VAULT_BACKUP_SECRET_ID=$secret \
        dc exec -T -e VAULT_BACKUP_ROLE_ID -e VAULT_BACKUP_SECRET_ID vault sh -c '
            set -e
            token=$(VAULT_TOKEN= vault write -field=token auth/approle/login \
                role_id="$VAULT_BACKUP_ROLE_ID" secret_id="$VAULT_BACKUP_SECRET_ID")
            VAULT_TOKEN=$token vault operator raft snapshot save /tmp/vault.snap'
    dc cp vault:/tmp/vault.snap "$out/vault.snap"
    dc exec -T vault rm -f /tmp/vault.snap
fi

say "checksums"
(
    cd "$out"
    if command -v sha256sum > /dev/null; then
        sha256sum ./* > SHA256SUMS
    else
        shasum -a 256 ./* > SHA256SUMS
    fi
)

if [ "$keep" -gt 0 ]; then
    say "keeping the $keep newest backups"
    ls -1 "$dir" | grep -E '^[0-9]{8}T[0-9]{6}Z$' | sort \
        | awk -v keep="$keep" '{ a[NR] = $0 } END { for (i = 1; i <= NR - keep; i++) print a[i] }' \
        | while read -r old; do rm -rf "${dir:?}/$old"; done
fi

echo "backup written to $out"
exit "$status"

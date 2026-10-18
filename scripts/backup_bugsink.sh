#!/usr/bin/env bash
# Back up the Bugsink database (error events, issues, users) of a production server to the
# sp-logs bucket. Run it on the server, in the deploy directory (cron line: see prod_init.sh).
#
# Usage: scripts/backup_bugsink.sh [--dir DIR] [--keep N]
#   --dir DIR   where to write (default: ./backups/bugsink)
#   --keep N    afterwards delete all but the N newest local copies (default: keep everything)
#
# Output: DIR/<UTC timestamp>.dump.age, an `age` encrypted pg_dump (custom format) of the
# `bugsink` database, encrypted to BACKUP_AGE_RECIPIENT of .env.prod (the same recipient as
# scripts/backup.sh). Bugsink stores its events in PostgreSQL (no object storage), so this
# dump is the whole error-tracking data. It is uploaded to BUGSINK_BACKUP_S3_URL (the sp-logs
# bucket) with its own write-only key (BUGSINK_BACKUP_S3_ACCESS_KEY / _SECRET_KEY,
# BUGSINK_BACKUP_S3_ENDPOINT_URL for a non-AWS provider). A failed encryption or upload fails
# the run. Needs `age` and, for the upload, the `aws` CLI on the host.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

ENV_FILE=.env.prod
COMPOSE_FILE=materials/docker-compose.prod.yaml
dir=backups/bugsink
keep=0

while [ $# -gt 0 ]; do
    case "$1" in
        --dir) dir=${2:?--dir needs a value}; shift 2 ;;
        --keep) keep=${2:?--keep needs a value}; shift 2 ;;
        -h | --help) sed -n '2,17p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

[ -f "$ENV_FILE" ] || { echo "$ENV_FILE not found in $ROOT" >&2; exit 1; }
get_env() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1; }
say() { printf '==> %s\n' "$*"; }
# BUGSINK_DB_MODE: `main` dumps from the main PostgreSQL (role ihsp), `dedicated` from the
# bugsink-db container (role bugsink, profile bugsink-dedicated).
mode=$(get_env BUGSINK_DB_MODE)
case "${mode:-main}" in
    main) db_service=postgres; db_user=ihsp; export COMPOSE_PROFILES= ;;
    dedicated) db_service=bugsink-db; db_user=bugsink; export COMPOSE_PROFILES=bugsink-dedicated ;;
    *) echo "BUGSINK_DB_MODE must be main or dedicated" >&2; exit 1 ;;
esac
dc() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }

recipient=$(get_env BACKUP_AGE_RECIPIENT)
s3_url=$(get_env BUGSINK_BACKUP_S3_URL)
[ -n "$recipient" ] || { echo "BACKUP_AGE_RECIPIENT is not set in $ENV_FILE" >&2; exit 1; }
command -v age > /dev/null || { echo "age is not installed (apt install age)" >&2; exit 1; }
if [ -n "$s3_url" ]; then
    command -v aws > /dev/null || { echo "BUGSINK_BACKUP_S3_URL is set but the aws CLI is not installed" >&2; exit 1; }
fi

stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$dir"
chmod 700 "$dir"
result="$dir/$stamp.dump.age"

say "PostgreSQL: bugsink"
dc exec -T "$db_service" pg_dump -U "$db_user" -Fc bugsink | age -r "$recipient" > "$result"
chmod 600 "$result"

if [ -n "$s3_url" ]; then
    say "uploading to $s3_url"
    endpoint=$(get_env BUGSINK_BACKUP_S3_ENDPOINT_URL)
    endpoint_args=()
    [ -n "$endpoint" ] && endpoint_args=(--endpoint-url "$endpoint")
    if ! AWS_ACCESS_KEY_ID=$(get_env BUGSINK_BACKUP_S3_ACCESS_KEY) \
        AWS_SECRET_ACCESS_KEY=$(get_env BUGSINK_BACKUP_S3_SECRET_KEY) \
        AWS_EC2_METADATA_DISABLED=true \
        aws s3 cp "$result" "${s3_url%/}/$stamp.dump.age" "${endpoint_args[@]}" > /dev/null; then
        echo "error: upload to $s3_url failed; the backup is only on this host" >&2
        exit 1
    fi
fi

if [ "$keep" -gt 0 ]; then
    say "keeping the $keep newest local copies"
    ls -1 "$dir" | grep -E '^[0-9]{8}T[0-9]{6}Z\.dump\.age$' | sort \
        | awk -v keep="$keep" '{ a[NR] = $0 } END { for (i = 1; i <= NR - keep; i++) print a[i] }' \
        | while read -r old; do rm -f "${dir:?}/$old"; done
fi

echo "backup written to $result"

#!/usr/bin/env bash
# Target side of the server-to-server migration. Run as root on the NEW server, after a
# fresh ihsp is installed there (scripts/cloud_deploy.sh <new-host> --init, same image tag).
#
# Usage: scripts/migrate_target.sh prepare [--host HOST] [--port 22]
#        scripts/migrate_target.sh finish ID
#        scripts/migrate_target.sh abort
#
# prepare  creates the restricted user `ihsp-migrate`, a temporary ed25519 key pair and an
#          authorized_keys entry that allows ONLY `rrsync -wo <incoming dir>` (write-only
#          rsync into one directory: no shell, no forwarding, no reads). It prints the
#          one-time pairing token for the admin page of the old server (Admin > Server
#          migration): the private key and this server's host key, base64url encoded.
#          The token is single use: `finish` and `abort` remove the key, so a leaked token
#          is worthless afterwards. Treat it like a password until then.
# finish   checks the received set (READY marker, SHA256SUMS), then restores it here:
#          the config, PostgreSQL (ihsp and hydra), Redis, the object store and the
#          backups. Vault is NOT unsealed for you: the script prints the commands.
# abort    removes the key and the received data.
#
# Environment: IHSP_ROOT (default /opt/ihsp).
set -euo pipefail
set +x

ROOT=${IHSP_ROOT:-/opt/ihsp}
INCOMING=$ROOT/incoming
SVC_USER=ihsp-migrate
HOME_DIR=/var/lib/$SVC_USER

say() { printf '==> %s\n' "$*" >&2; }
die() { echo "error: $*" >&2; exit 1; }
dc() { docker compose --env-file "$ROOT/.env.prod" -f "$ROOT/materials/docker-compose.prod.yaml" "$@"; }

need_root() { [ "$(id -u)" -eq 0 ] || die "run as root"; }

rrsync_path() {
    command -v rrsync || ls /usr/share/doc/rsync/scripts/rrsync 2> /dev/null || true
}

revoke_key() {
    rm -f "$HOME_DIR/.ssh/authorized_keys"
}

prepare() {
    local host="" port=22
    while [ $# -gt 0 ]; do
        case "$1" in
            --host) host=${2:?--host needs a value}; shift 2 ;;
            --port) port=${2:?--port needs a value}; shift 2 ;;
            *) die "unknown argument: $1" ;;
        esac
    done
    need_root
    command -v rsync > /dev/null || die "rsync is not installed (apt install rsync)"
    local rr
    rr=$(rrsync_path)
    [ -n "$rr" ] || die "rrsync is not installed (it ships with the rsync package)"
    [ -f "$ROOT/.env.prod" ] || die "no fresh install in $ROOT (run cloud_deploy.sh --init)"
    id "$SVC_USER" > /dev/null 2>&1 ||
        useradd --system --home-dir "$HOME_DIR" --create-home --shell /bin/sh "$SVC_USER"
    passwd -l "$SVC_USER" > /dev/null 2>&1 || true
    install -d -m 0700 -o "$SVC_USER" -g "$SVC_USER" "$INCOMING" "$HOME_DIR/.ssh"
    local tmp
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    ssh-keygen -q -t ed25519 -N "" -C "ihsp-migration" -f "$tmp/key"
    printf 'restrict,command="%s -wo %s" %s\n' "$rr" "$INCOMING" "$(cat "$tmp/key.pub")" \
        > "$HOME_DIR/.ssh/authorized_keys"
    chown "$SVC_USER:$SVC_USER" "$HOME_DIR/.ssh/authorized_keys"
    chmod 600 "$HOME_DIR/.ssh/authorized_keys"
    local host_key
    host_key=$(awk '{ print $1 " " $2 }' /etc/ssh/ssh_host_ed25519_key.pub)
    local token
    token=$(python3 - "$tmp/key" "$SVC_USER" "$port" "$host_key" <<'PY'
import base64, json, sys

key, user, port, host_key = sys.argv[1:5]
body = {"user": user, "port": int(port), "key": open(key).read(), "host_key": host_key}
raw = base64.urlsafe_b64encode(json.dumps(body).encode()).decode().rstrip("=")
print("ihsp-pair-v1." + raw)
PY
    )
    say "ready. Enter on the old server (Admin > Server migration):"
    [ -n "$host" ] && say "  target host: $host (port $port)"
    say "  pairing token (single use, shown once, keep it secret):"
    printf '%s\n' "$token"
}

finish() {
    local id=${1:?usage: migrate_target.sh finish ID}
    need_root
    local dir=$INCOMING/$id
    [ -f "$dir/READY" ] || die "$dir/READY is missing: the transfer is not complete"
    (cd "$dir" && sha256sum -c SHA256SUMS > /dev/null) || die "checksum mismatch in $dir"
    revoke_key
    say "checksums ok; the pairing key is revoked"
    cd "$ROOT"
    say "saving this server's own config"
    tar -cf "$ROOT/config-before-migration.tar" .env.prod secrets materials
    dc down
    tar -C "$ROOT" -xf "$dir/config.tar"
    dc up -d postgres redis s3 vault
    say "PostgreSQL"
    dc exec -T postgres pg_restore -U ihsp -d ihsp --clean --if-exists --no-owner \
        < "$dir/ihsp.dump"
    dc exec -T postgres pg_restore -U ihsp -d hydra --clean --if-exists --no-owner \
        < "$dir/hydra.dump"
    say "object store"
    docker cp - "$(dc ps -q s3):/data" < "$dir/s3_data.tar"
    say "Redis"
    dc stop redis
    docker cp "$dir/redis.rdb" "$(dc ps -aq redis):/data/dump.rdb"
    dc start redis
    [ -f "$dir/backups.tar" ] && tar -C "$ROOT" -xf "$dir/backups.tar"
    cat >&2 <<MSG

Restored. Left to do by hand (the unseal keys never leave the old server):
  1. Unseal Vault with the OLD server's keys:      scripts/prod_init.sh unseal
  2. Restore the Vault data:                        docker cp $dir/vault.snap vault:/tmp/
       dc exec vault vault operator raft snapshot restore -force /tmp/vault.snap
  3. Start everything:                              docker compose ... up -d --wait
  4. Check https://<domain>/health on this server, then switch the DNS to it.
  5. Remove $INCOMING/$id (it holds a plain copy of the data).
MSG
}

abort() {
    need_root
    revoke_key
    rm -rf "${INCOMING:?}"/*
    say "key revoked, received data removed"
}

case "${1:-}" in
    prepare) shift; prepare "$@" ;;
    finish) shift; finish "$@" ;;
    abort) abort ;;
    *) sed -n '2,8p' "$0"; exit 2 ;;
esac

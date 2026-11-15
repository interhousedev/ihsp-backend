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
# finish   freezes the received set: revokes the key, ends the migration user's sessions and
#          moves incoming/ID into a root-only staging dir, then checks it there (READY
#          marker, SHA256SUMS, every dump readable) before anything is stopped. Then it
#          restores the staged copy here: the config, PostgreSQL (ihsp, hydra, bugsink, with
#          their owners and the copied passwords), Redis, the object store (replaced, not
#          merged), the Vault snapshot and the backups. Afterwards Vault needs the OLD
#          server's unseal keys. A restored set is never restored twice.
# abort    removes the key. Before a restore started it also removes the received data;
#          after, it stops this server's stack and keeps every recovery artifact.
#
# prepare, finish and abort take one lock: they never run at the same time.
#
# Environment: IHSP_ROOT (default /opt/ihsp).
set -euo pipefail
set +x

ROOT=${IHSP_ROOT:-/opt/ihsp}
INCOMING=$ROOT/incoming
STAGE=$ROOT/migration-staging
SCRIPTS=$(cd "$(dirname "$0")" && pwd)
VAULT_SKIPPED=0
SVC_USER=ihsp-migrate
HOME_DIR=${IHSP_MIGRATE_HOME:-/var/lib/$SVC_USER}
HOST_KEY=${IHSP_SSH_HOST_KEY:-/etc/ssh/ssh_host_ed25519_key.pub}

say() { printf '==> %s\n' "$*" >&2; }
die() { echo "error: $*" >&2; exit 1; }
dc() { docker compose --env-file "$ROOT/.env.prod" -f "$ROOT/materials/docker-compose.prod.yaml" "$@"; }
get_env() { sed -n "s/^$1=//p" "$ROOT/.env.prod" | tail -n 1; }

need_root() { [ "$(id -u)" -eq 0 ] || die "run as root"; }

rrsync_path() {
    command -v rrsync || ls /usr/share/doc/rsync/scripts/rrsync 2> /dev/null || true
}

revoke_key() {
    rm -f "$HOME_DIR/.ssh/authorized_keys"
    # A transfer still running would keep writing after the key is gone.
    pkill -KILL -u "$SVC_USER" 2> /dev/null || true
}

lock() {
    exec 9> "$ROOT/.migrate.lock"
    flock -n 9 || die "another migrate_target.sh is running"
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
    lock
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
    # Expanded now: the local is gone when the EXIT trap runs (set -u would fail there and
    # leave the private key behind in /tmp).
    # shellcheck disable=SC2064
    trap "rm -rf '$tmp'" EXIT
    ssh-keygen -q -t ed25519 -N "" -C "ihsp-migration" -f "$tmp/key"
    printf 'restrict,command="%s -wo %s" %s\n' "$rr" "$INCOMING" "$(cat "$tmp/key.pub")" \
        > "$HOME_DIR/.ssh/authorized_keys"
    chown "$SVC_USER:$SVC_USER" "$HOME_DIR/.ssh/authorized_keys"
    chmod 600 "$HOME_DIR/.ssh/authorized_keys"
    local host_key
    host_key=$(awk '{ print $1 " " $2 }' "$HOST_KEY")
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
    case "$id" in */* | .* | "") die "bad ID: $id" ;; esac
    need_root
    lock
    local dir=$STAGE/$id
    [ ! -f "$dir/RESTORED" ] || die "$id is already restored; nothing to do"
    [ ! -f "$dir/STARTED" ] || die "a restore of $id started and did not finish; run abort"
    if [ ! -d "$dir" ]; then
        [ -f "$INCOMING/$id/READY" ] || die "$INCOMING/$id/READY is missing: the transfer is not complete"
        # Freeze: from here the sender can no longer touch what gets checked and restored.
        revoke_key
        say "the pairing key is revoked"
        install -d -m 0700 -o root -g root "$STAGE"
        mv "$INCOMING/$id" "$dir"
        chown -R root:root "$dir"
        chmod -R go-rwx "$dir"
    fi
    [ -z "$(find "$dir" -type l)" ] || die "$dir holds symlinks; refusing it"
    [ -f "$dir/READY" ] || die "$dir/READY is missing: the transfer is not complete"
    (cd "$dir" && sha256sum -c SHA256SUMS > /dev/null) || die "checksum mismatch in $dir"
    check_dumps "$dir"
    say "checksums ok"
    cd "$ROOT"
    if [ -e "$ROOT/config-before-migration.tar" ]; then
        say "keeping the existing config-before-migration.tar"
    else
        say "saving this server's own config"
        (umask 077 && tar -cf "$ROOT/config-before-migration.tar" .env.prod secrets materials)
    fi
    chmod 600 "$ROOT/config-before-migration.tar"
    touch "$dir/STARTED"
    dc --profile '*' down
    tar -C "$ROOT" -xf "$dir/config.tar"
    # The Vault keys of THIS server stay valid until the snapshot replaces its data.
    local keys=$ROOT/secrets/vault-init.txt
    dc up -d --wait postgres redis vault
    restore_postgres "$dir"
    restore_bugsink "$dir"
    restore_objects "$dir"
    restore_redis "$dir"
    restore_vault "$dir" "$keys"
    if [ -f "$dir/backups.tar" ]; then tar -C "$ROOT" -xf "$dir/backups.tar"; fi
    touch "$dir/RESTORED"
    local start="BUGSINK_DB_HOST=postgres"
    [ "$(get_env BUGSINK_DB_MODE)" = dedicated ] &&
        start="COMPOSE_PROFILES=bugsink-dedicated BUGSINK_DB_HOST=bugsink-db"
    cat >&2 <<MSG

Restored. Left to do by hand (the unseal keys never leave the old server):
  1. Unseal Vault with the OLD server's keys:      scripts/prod_init.sh unseal
  2. Start everything:
       cd $ROOT && $start docker compose --env-file .env.prod \\
         -f materials/docker-compose.prod.yaml up -d --wait
  3. Check https://<domain>/health on this server, then switch the DNS to it.
  4. Remove $dir (it holds a plain copy of the data).
MSG
    if [ "$VAULT_SKIPPED" = 1 ]; then
        echo "error: Vault was NOT restored; restore $dir/vault.snap by hand (scripts/restore.sh --with-vault)" >&2
        exit 3
    fi
}

# Everything a restore needs, checked before this server's stack goes down.
check_dumps() {
    local dir=$1 f
    for f in config.tar ihsp.dump hydra.dump redis.rdb; do
        [ -s "$dir/$f" ] || die "$dir/$f is missing or empty"
    done
    dc up -d --wait postgres
    for f in ihsp.dump hydra.dump bugsink.dump; do
        [ -f "$dir/$f" ] || continue
        dc exec -T postgres pg_restore -l < "$dir/$f" > /dev/null || die "$dir/$f is not a readable dump"
    done
}

# pg_dump does not carry roles: the roles of this server keep this server's passwords, so
# they get the passwords of the copied .env.prod, then each database is recreated empty and
# restored with its original owners (a non-owner hydra could not read its own tables).
restore_postgres() {
    local dir=$1
    say "PostgreSQL"
    POSTGRES_PASSWORD=$(get_env POSTGRES_PASSWORD) HYDRA_DB_PASSWORD=$(get_env HYDRA_DB_PASSWORD) \
        BUGSINK_DB_PASSWORD=$(get_env BUGSINK_DB_PASSWORD) \
        dc exec -T -e POSTGRES_PASSWORD -e HYDRA_DB_PASSWORD -e BUGSINK_DB_PASSWORD postgres \
        psql -v ON_ERROR_STOP=1 -U ihsp -d postgres -q <<'SQL'
\getenv pw POSTGRES_PASSWORD
ALTER ROLE ihsp PASSWORD :'pw';
\getenv pw HYDRA_DB_PASSWORD
ALTER ROLE hydra PASSWORD :'pw';
\getenv pw BUGSINK_DB_PASSWORD
SELECT EXISTS (SELECT FROM pg_roles WHERE rolname = 'bugsink') AND :'pw' <> '' AS bugsink \gset
\if :bugsink
ALTER ROLE bugsink PASSWORD :'pw';
\endif
SQL
    restore_db postgres ihsp ihsp ihsp "$dir/ihsp.dump"
    restore_db postgres ihsp hydra hydra "$dir/hydra.dump"
}

# restore_db <service> <superuser> <database> <owner> <dump>
# The profile only makes bugsink-db addressable; `exec` starts nothing.
restore_db() {
    local svc=$1 su=$2 db=$3 owner=$4 dump=$5
    local -a dcp=(dc --profile bugsink-dedicated exec -T "$svc")
    "${dcp[@]}" dropdb -U "$su" --if-exists --force "$db"
    "${dcp[@]}" createdb -U "$su" -O "$owner" "$db"
    "${dcp[@]}" pg_restore -U "$su" -d "$db" --exit-on-error < "$dump"
}

restore_bugsink() {
    local dir=$1
    [ -f "$dir/bugsink.dump" ] || return 0
    say "Bugsink"
    if [ "$(get_env BUGSINK_DB_MODE)" = dedicated ]; then
        dc --profile bugsink-dedicated up -d --wait bugsink-db
        # Its superuser got this server's password at init; the copied .env.prod has another.
        BUGSINK_DB_PASSWORD=$(get_env BUGSINK_DB_PASSWORD) dc --profile bugsink-dedicated \
            exec -T -e BUGSINK_DB_PASSWORD bugsink-db psql -v ON_ERROR_STOP=1 -U bugsink \
            -d postgres -q <<'SQL'
\getenv pw BUGSINK_DB_PASSWORD
ALTER ROLE bugsink PASSWORD :'pw';
SQL
        restore_db bugsink-db bugsink bugsink bugsink "$dir/bugsink.dump"
    else
        # A fresh install may predate Bugsink: create the role if missing (as cloud_deploy.sh).
        BUGSINK_PW=$(get_env BUGSINK_DB_PASSWORD) dc exec -T -e BUGSINK_PW postgres sh -c \
            'psql -v ON_ERROR_STOP=1 -U ihsp -d postgres -q -v pw="$BUGSINK_PW"' <<'SQL'
SELECT format('CREATE ROLE bugsink LOGIN PASSWORD %L', :'pw') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bugsink') \gexec
SELECT format('ALTER ROLE bugsink LOGIN PASSWORD %L', :'pw') \gexec
SQL
        restore_db postgres ihsp bugsink bugsink "$dir/bugsink.dump"
    fi
}

restore_objects() {
    local dir=$1 cid
    [ -f "$dir/s3_data.tar" ] || { say "object store: external, nothing to restore"; return 0; }
    say "object store"
    dc up -d --wait s3
    cid=$(dc ps -q s3)
    dc stop s3
    # Replace, not merge: this server's own (empty) bucket metadata must not survive.
    dc run --rm --no-deps -T --entrypoint sh s3 -c 'find /data -mindepth 1 -delete' > /dev/null
    docker cp - "$cid:/data" < "$dir/s3_data.tar"
    dc start s3
}

# The loader (scripts/redis_load_rdb.sh, shared with restore.sh) fails on any step it cannot
# confirm: no PONG, CONFIG SET not OK, no finished AOF rewrite with its manifest.
restore_redis() {
    local dir=$1
    say "Redis"
    dc stop redis
    dc run --rm --no-deps -T -v "$dir:/restore:ro" --entrypoint sh redis \
        -c "$(cat "$SCRIPTS/redis_load_rdb.sh")"
    dc up -d --wait redis
}

# The snapshot replaces this server's Vault data; afterwards only the OLD server's unseal
# keys open it. This server's own keys are needed once more, to unseal it for the restore.
restore_vault() {
    local dir=$1 keys=$2 token snap key
    if [ ! -f "$keys" ] || [ ! -s "$dir/vault.snap" ]; then
        say "Vault: no $keys or no vault.snap; skipped"
        VAULT_SKIPPED=1
        return 0
    fi
    say "Vault"
    # The key goes through stdin into a 0600 file inside the container, never into an argv.
    sed -n 's/^Unseal Key [0-9]*: //p' "$keys" | head -n 3 | while IFS= read -r key; do
        printf '%s\n' "$key" | dc exec -T vault sh -c '
            umask 077
            f=$(mktemp /tmp/unseal.XXXXXX) || exit 1
            read -r key
            printf "{\"key\":\"%s\"}" "$key" > "$f"
            wget -q -O /dev/null --header "Content-Type: application/json" \
                --post-file "$f" http://127.0.0.1:8200/v1/sys/unseal
            rc=$?
            rm -f "$f"
            exit $rc'
    done
    token=$(sed -n 's/^Initial Root Token: //p' "$keys")
    # Not `compose cp`: it creates the file as root and the vault user could not read it.
    snap=$(dc exec -T vault sh -c 'f=$(mktemp /tmp/vault-restore.XXXXXX) && cat > "$f" && echo "$f"' \
        < "$dir/vault.snap")
    VAULT_TOKEN=$token dc exec -T -e VAULT_TOKEN vault \
        vault operator raft snapshot restore -force "$snap"
    dc exec -T vault rm -f "$snap"
    # Those keys and that token are void now: `prod_init.sh unseal` must ask for the old ones.
    mv "$keys" "$ROOT/secrets/vault-init.before-migration.txt"
}

abort() {
    need_root
    lock
    revoke_key
    if compgen -G "$STAGE/*/STARTED" > /dev/null; then
        # Past the point of no return: this server holds (part of) the old server's data.
        say "a restore had started: stopping this server's stack"
        cd "$ROOT"
        dc --profile '*' down
        cat >&2 <<MSG

Key revoked; this server's stack is stopped. Kept for recovery: $STAGE,
$ROOT/config-before-migration.tar and secrets/vault-init.before-migration.txt (if any).
Before you resume the OLD server, confirm nothing runs here:
  cd $ROOT && docker compose --env-file .env.prod -f materials/docker-compose.prod.yaml ps
Two live copies would both write (mail, bot, schedules) and diverge.
MSG
        return 0
    fi
    rm -rf "${INCOMING:?}"/* "${STAGE:?}"/*
    say "key revoked, received data removed (no restore had started)"
}

case "${1:-}" in
    prepare) shift; prepare "$@" ;;
    finish) shift; finish "$@" ;;
    abort) abort ;;
    *) sed -n '2,8p' "$0"; exit 2 ;;
esac

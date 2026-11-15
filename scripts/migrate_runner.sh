#!/usr/bin/env bash
# Host-side runner of the server-to-server migration (the source server).
# Runs as root on the HOST, never in a container: the api container only drops a 0600
# request file into a bind-mounted directory, a systemd path unit starts this script, and
# the script does the privileged work. The api never gets the Docker socket or root.
#
# Usage: scripts/migrate_runner.sh install            install the systemd units (once, root)
#        scripts/migrate_runner.sh run [--dry-run]    handle request.json / command.json
#
# Shared directory (default /opt/ihsp/data/migration, the api sees it as /migration):
#   request.json  written by the api (0600): id, target, one-time pairing token. Read once,
#                 then deleted.
#   command.json  written by the api: {"id", "action": "cancel" | "resume"}.
#   status.json   written by this script (no secrets): id, state, step, steps_done, error.
#
# Steps (the admin page shows them as a checklist): stop_services, dump_postgres,
# snapshot_redis, copy_objects, copy_config, copy_vault, copy_backups, transfer, verify.
# Source data is never deleted or modified: Postgres, Redis, the object store and Vault are
# only read; worker, scheduler, bot and mail are stopped (restarted on failure or cancel).
# The staged copy (a plain copy of the whole database and the keys!) lives in a root-only
# work directory and is removed when the run ends. The pairing token is decoded into a
# 0600 key file in that directory; it is never printed, logged or written to status.json.
#
# Environment: IHSP_ROOT (default /opt/ihsp), IHSP_MIGRATION_DIR, IHSP_MIGRATION_WORK
# (default /var/lib/ihsp-migration). --dry-run walks the steps without touching anything.
set -euo pipefail
set +x
umask 077

ROOT=${IHSP_ROOT:-/opt/ihsp}
DIR=${IHSP_MIGRATION_DIR:-$ROOT/data/migration}
WORK=${IHSP_MIGRATION_WORK:-/var/lib/ihsp-migration}
STEPS=(stop_services dump_postgres snapshot_redis copy_objects copy_config copy_vault
    copy_backups transfer verify)
RESTART=(worker scheduler bot mail)
DRY=0
ID=""
ERR_MSG=""
DONE=()
CURRENT=""
FINISHED=0
LOCKED=0

say() { printf '==> %s\n' "$*"; }

json() {
    # json <python expression over argv>: tiny JSON helper (python3 ships with the host).
    python3 -c "$@"
}

write_status() {
    # write_status <state> [error]
    local state=$1 error=${2:-}
    [ -n "$ID" ] || return 0
    python3 - "$DIR/status.json" "$ID" "$state" "$CURRENT" "$error" "$DRY" "${DONE[*]:-}" <<'PY'
import json, os, sys, tempfile
from datetime import datetime, timezone

path, mid, state, step, error, dry, done = sys.argv[1:8]
body = {
    "id": mid,
    "state": state,
    "step": step or None,
    "steps_done": done.split(),
    "error": error or None,
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "dry_run": dry == "1",
}
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".status-")
with os.fdopen(fd, "w") as handle:
    json.dump(body, handle)
os.chmod(tmp, 0o644)
os.replace(tmp, path)
PY
}

dc() { docker compose --env-file "$ROOT/.env.prod" -f "$ROOT/materials/docker-compose.prod.yaml" "$@"; }

restart_services() {
    [ "$DRY" -eq 1 ] && { say "dry-run: would restart ${RESTART[*]}"; return 0; }
    (cd "$ROOT" && dc start "${RESTART[@]}") || true
}

cleanup() {
    local code=$?
    if [ "$FINISHED" -ne 1 ] && [ -n "$ID" ]; then
        write_status failed "${ERR_MSG:-step ${CURRENT:-start} failed}" || true
        restart_services
    fi
    if [ -n "${RUN:-}" ] && [ -d "$RUN" ]; then
        rm -rf "${RUN:?}"
    fi
    [ "$LOCKED" -eq 1 ] && rm -rf "$WORK/lock.d"
    exit "$code"
}

take_lock() {
    mkdir -p "$WORK"
    chmod 700 "$WORK"
    if mkdir "$WORK/lock.d" 2> /dev/null; then
        echo $$ > "$WORK/lock.d/pid"
        LOCKED=1
        return 0
    fi
    local pid
    pid=$(cat "$WORK/lock.d/pid" 2> /dev/null || true)
    if [ -n "$pid" ] && kill -0 "$pid" 2> /dev/null; then
        return 1 # another run is active; it also handles command.json
    fi
    rm -rf "$WORK/lock.d"
    mkdir "$WORK/lock.d"
    echo $$ > "$WORK/lock.d/pid"
    LOCKED=1
}

command_action() {
    [ -f "$DIR/command.json" ] || return 0
    json 'import json,sys; print(json.load(open(sys.argv[1])).get("action",""))' \
        "$DIR/command.json" 2> /dev/null || true
}

command_id() {
    json 'import json,sys; print(json.load(open(sys.argv[1])).get("id",""))' \
        "$DIR/command.json" 2> /dev/null || true
}

cancel_run() {
    say "cancelled: restarting ${RESTART[*]}"
    restart_services
    [ -n "$ID" ] || ID=$(command_id)
    CURRENT=""
    write_status cancelled
    rm -f "$DIR/command.json" "$DIR/request.json"
    FINISHED=1
    exit 0
}

check_cancel() {
    case "$(command_action)" in
        cancel | resume) cancel_run ;;
    esac
}

load_request() {
    RUN="$WORK/run-$$"
    mkdir -p "$RUN"
    local fields
    if ! fields=$(python3 - "$DIR/request.json" "$RUN" <<'PY'
import base64, json, os, sys

req = json.load(open(sys.argv[1]))
run = sys.argv[2]
token = req["pairing_token"]
prefix = "ihsp-pair-v1."
if not token.startswith(prefix):
    raise SystemExit(3)
raw = token[len(prefix):]
body = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
import re

user, key, host_key = body["user"], body["key"], body["host_key"]
port = int(req["target_port"]) if "target_port" in req else int(body.get("port") or 22)
host = req["target_host"]
rid = str(req["id"])
# The request file is trusted only after this check: no leading "-", no whitespace.
if (
    not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", rid)
    or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user)
    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,252}", host)
    or not 1 <= port <= 65535
    or not re.fullmatch(r"[A-Za-z0-9+/=@. -]{1,2048}", host_key)
):
    raise SystemExit(3)
with open(os.path.join(run, "id"), "w", opener=lambda p, f: os.open(p, f, 0o600)) as h:
    h.write(key if key.endswith("\n") else key + "\n")
with open(os.path.join(run, "known_hosts"), "w") as h:
    h.write((f"{host} " if port == 22 else f"[{host}]:{port} ") + host_key + "\n")
print(req["id"], host, port, user, "1" if req.get("dry_run") else "0")
PY
    ); then
        # The message never carries the token or the decoder's exception text.
        ID=$(json 'import json,sys; print(json.load(open(sys.argv[1])).get("id",""))' \
            "$DIR/request.json" 2> /dev/null || true)
        ERR_MSG="the pairing token is invalid"
        rm -f "$DIR/request.json"
        return 1
    fi
    rm -f "$DIR/request.json"
    read -r ID HOST PORT USER REQ_DRY <<< "$fields"
    if [ "$REQ_DRY" = "1" ]; then DRY=1; fi
}

step_stop_services() {
    (cd "$ROOT" && dc stop "${RESTART[@]}")
}

step_dump_postgres() {
    (cd "$ROOT" && dc exec -T postgres pg_dump -U ihsp -Fc ihsp > "$OUT/ihsp.dump")
    (cd "$ROOT" && dc exec -T postgres pg_dump -U ihsp -Fc hydra > "$OUT/hydra.dump")
}

step_snapshot_redis() {
    # Holds the pending taskiq tasks, the rate limits and the sessions.
    local last now=""
    last=$(cd "$ROOT" && dc exec -T redis redis-cli LASTSAVE | tr -d '\r')
    (cd "$ROOT" && dc exec -T redis redis-cli BGSAVE > /dev/null)
    for _ in $(seq 1 120); do
        now=$(cd "$ROOT" && dc exec -T redis redis-cli LASTSAVE | tr -d '\r')
        [ "$now" != "$last" ] && break
        sleep 1
    done
    if [ "$now" = "$last" ]; then ERR_MSG="the Redis snapshot did not finish"; return 1; fi
    (cd "$ROOT" && dc cp redis:/data/dump.rdb "$OUT/redis.rdb")
}

step_copy_objects() {
    local cid
    cid=$(cd "$ROOT" && dc ps -q s3)
    [ -n "$cid" ] || { ERR_MSG="the s3 service is not running"; return 1; }
    docker cp "$cid:/data/." - > "$OUT/s3_data.tar"
}

step_copy_config() {
    tar -C "$ROOT" -cf "$OUT/config.tar" --exclude=secrets/vault-init.txt .env.prod secrets materials
}

step_copy_vault() {
    local role secret sealed
    role=$(sed -n 's/^VAULT_BACKUP_ROLE_ID=//p' "$ROOT/.env.prod" | tail -n 1)
    secret=$(sed -n 's/^VAULT_BACKUP_SECRET_ID=//p' "$ROOT/.env.prod" | tail -n 1)
    sealed=$(cd "$ROOT" && dc exec -T vault vault status 2> /dev/null |
        awk '$1 == "Sealed" { print $2 }' || true)
    if [ -z "$role" ] || [ -z "$secret" ] || [ "$sealed" != "false" ]; then
        ERR_MSG="Vault is sealed or has no backup AppRole (scripts/prod_init.sh)"
        return 1
    fi
    (cd "$ROOT" && VAULT_BACKUP_ROLE_ID=$role VAULT_BACKUP_SECRET_ID=$secret \
        dc exec -T -e VAULT_BACKUP_ROLE_ID -e VAULT_BACKUP_SECRET_ID vault sh -c '
            set -e
            token=$(VAULT_TOKEN= vault write -field=token auth/approle/login \
                role_id="$VAULT_BACKUP_ROLE_ID" secret_id="$VAULT_BACKUP_SECRET_ID")
            VAULT_TOKEN=$token vault operator raft snapshot save /tmp/vault.snap')
    (cd "$ROOT" && dc cp vault:/tmp/vault.snap "$OUT/vault.snap")
    (cd "$ROOT" && dc exec -T vault rm -f /tmp/vault.snap)
}

step_copy_backups() {
    if [ -d "$ROOT/backups" ]; then
        tar -C "$ROOT" -cf "$OUT/backups.tar" backups
    fi
}

step_transfer() {
    (cd "$OUT" && sha256sum ./* > SHA256SUMS)
    echo "$ID" > "$OUT/READY"
    local ssh_cmd
    ssh_cmd="ssh -i $RUN/id -p $PORT -o IdentitiesOnly=yes -o BatchMode=yes"
    ssh_cmd="$ssh_cmd -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$RUN/known_hosts"
    # READY goes last: the target refuses a set without it.
    rsync -a --partial --exclude READY -e "$ssh_cmd" -- "$OUT/" "$USER@$HOST:$ID/"
    rsync -a -e "$ssh_cmd" -- "$OUT/READY" "$USER@$HOST:$ID/READY"
}

step_verify() {
    (cd "$OUT" && sha256sum -c SHA256SUMS > /dev/null)
}

run_step() {
    local name=$1
    CURRENT=$name
    write_status running
    check_cancel
    if [ "$DRY" -eq 1 ]; then
        say "dry-run: $name"
    else
        say "$name"
        "step_$name"
    fi
    DONE+=("$name")
    CURRENT=""
}

do_run() {
    case "$(command_action)" in
        "" | cancel | resume) ;;
        *) rm -f "$DIR/command.json" ;; # unknown action: drop it so the path unit settles
    esac
    if [ -f "$DIR/command.json" ] && [ -z "$(command_action)" ]; then
        rm -f "$DIR/command.json"
    fi
    if [ ! -f "$DIR/request.json" ] && [ -z "$(command_action)" ]; then
        return 0
    fi
    take_lock || return 0
    trap cleanup EXIT
    if [ -f "$DIR/command.json" ] && [ -f "$DIR/request.json" ]; then
        case "$(command_action)" in cancel | resume) cancel_run ;; esac
    fi
    if [ ! -f "$DIR/request.json" ]; then
        case "$(command_action)" in
            cancel | resume) cancel_run ;;
            *) rm -f "$DIR/command.json"; FINISHED=1; return 0 ;;
        esac
    fi
    load_request
    OUT="$RUN/out"
    mkdir -p "$OUT"
    write_status running
    for name in "${STEPS[@]}"; do
        run_step "$name"
    done
    write_status completed
    FINISHED=1
    say "migration $ID finished: the source stays read-only"
}

do_install() {
    [ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
    install -d -m 0700 -o 10001 -g 10001 "$DIR"
    install -d -m 0700 "$WORK"
    sed "s#/opt/ihsp#$ROOT#g" "$ROOT/materials/systemd/ihsp-migration.service" \
        > /etc/systemd/system/ihsp-migration.service
    sed "s#/opt/ihsp#$ROOT#g" "$ROOT/materials/systemd/ihsp-migration.path" \
        > /etc/systemd/system/ihsp-migration.path
    systemctl daemon-reload
    systemctl enable --now ihsp-migration.path
    say "installed: ihsp-migration.path watches $DIR"
}

mode=${1:-}
[ $# -gt 0 ] && shift
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY=1 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done
case "$mode" in
    run) mkdir -p "$DIR"; do_run ;;
    install) do_install ;;
    *) sed -n '2,13p' "$0"; exit 2 ;;
esac

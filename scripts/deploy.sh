#!/usr/bin/env bash
# Deploy a released image tag to the production server configured in deploy.local.env.
#
# Usage: scripts/deploy.sh --tag TAG [--yes] [--push-env] [--no-pull]
#   --tag TAG    required: 1.2.0, sha-<40 hex>, latest
#   --yes        do not ask for confirmation
#   --push-env   overwrite the server's .env.prod with the local one
#   --no-pull    do not pull images
# Config: deploy.local.env (see deploy.local.env.sample): IHSP_DEPLOY_HOST, IHSP_REMOTE_DIR,
# IHSP_DEPLOY_STABLE_SECS. The work is done by scripts/cloud_deploy.sh: pre-migration
# database dump, migrations, services up, a stability gate, and an automatic rollback to the
# previous TAG if the gate fails (migrations are forward-only; the database is not restored).
set -euo pipefail
cd "$(dirname "$0")/.."

tag=
yes=0
extra=()
while [ $# -gt 0 ]; do
    case "$1" in
        --tag) tag=${2:?--tag needs a value}; shift 2 ;;
        --yes | -y) yes=1; shift ;;
        --push-env | --no-pull) extra+=("$1"); shift ;;
        -h | --help) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

cfg=deploy.local.env
[ -f "$cfg" ] || { echo "$cfg not found: copy deploy.local.env.sample" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
. "./$cfg"
set +a
[ -n "${IHSP_DEPLOY_HOST:-}" ] || { echo "IHSP_DEPLOY_HOST is not set in $cfg" >&2; exit 1; }
[ -n "$tag" ] || { echo "--tag is required (see --help)" >&2; exit 2; }
case "$tag" in
    *[!A-Za-z0-9._-]*) echo "invalid tag: $tag" >&2; exit 2 ;;
esac
export IHSP_REMOTE_DIR=${IHSP_REMOTE_DIR:-/opt/ihsp}

echo "Deploy plan:"
echo "  host:      $IHSP_DEPLOY_HOST"
echo "  directory: $IHSP_REMOTE_DIR"
echo "  tag:       $tag"
echo "  steps:     copy files, pull, pre-migration dump, migrate, up --wait,"
echo "             stability gate (${IHSP_DEPLOY_STABLE_SECS:-60}s), rollback on failure"
if [ "$yes" -ne 1 ]; then
    read -r -p "Proceed? [y/N] " answer
    case "$answer" in y | Y | yes) ;; *) echo "aborted"; exit 1 ;; esac
fi

exec scripts/cloud_deploy.sh "$IHSP_DEPLOY_HOST" --tag "$tag" ${extra[@]+"${extra[@]}"}

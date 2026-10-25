#!/usr/bin/env bash
# Run the CI checks locally, with the same commands as .github/workflows/{lint,test,security,codeql}.yml.
#
#   scripts/ci_local.sh [STAGE...] [--fast]
#
# Stages (default: lint test openapi security):
#   lint       black, isort, flake8, mypy (scripts/style_check.sh)
#   unit       the unit tests only (tests/*/unit), no services
#   test       the whole pytest suite against the dev compose services (starts them, stops them after)
#   openapi    openapi/openapi.json matches the exported document
#   security   scripts/security_scan.sh (gitleaks, trivy, semgrep, osv-scanner, pip-audit, bandit, CodeQL)
#
#   --fast     lint unit openapi: what to run before every push
#
# Every stage runs even when an earlier one fails; the summary lists the failures and the exit code is
# non-zero if there were any. Logs: reports/ci-local/<stage>.log (git-ignored). Stages run one at a time
# (Docker has little memory).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
LOGS="$ROOT/reports/ci-local"
mkdir -p "$LOGS"
COMPOSE=(docker compose -f materials/docker-compose.dev.yaml)

usage() { sed -n '2,/^set -uo/{/^set -uo/d;s/^# \{0,1\}//;p;}' "${BASH_SOURCE[0]}"; }

STAGES=()
for a in "$@"; do
  case "$a" in
    -h|--help) usage; exit 0 ;;
    --fast) STAGES+=(lint unit openapi) ;;
    lint|unit|test|openapi|security) STAGES+=("$a") ;;
    *) echo "unknown stage or option '$a' (see --help)" >&2; exit 2 ;;
  esac
done
[[ ${#STAGES[@]} -gt 0 ]] || STAGES=(lint test openapi security)

RESULTS=() FAILED=0
# check <name> <cmd...>: run one check, log it, record PASS/FAIL.
check() {
  local name=$1 rc=0 start
  shift
  start=$(date +%s)
  printf '  %-10s' "$name"
  "$@" >"$LOGS/$name.log" 2>&1 || rc=$?
  local took=$(( $(date +%s) - start ))
  if [[ $rc -eq 0 ]]; then
    echo "ok (${took}s)"; RESULTS+=("PASS  $name")
  else
    echo "FAIL (exit $rc, ${took}s) -> reports/ci-local/$name.log"; RESULTS+=("FAIL  $name"); FAILED=1
  fi
}

jwt_key() {
  [[ -f materials/dev-keys/jwt-bearer.pem ]] && return 0
  mkdir -p materials/dev-keys
  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out materials/dev-keys/jwt-bearer.pem
}
stage_lint() { uv sync --frozen && scripts/style_check.sh; }
stage_unit() { uv sync --frozen && jwt_key && uv run pytest -q -p no:cacheprovider tests/*/unit; }
stage_test() {
  uv sync --frozen && jwt_key || return 1
  "${COMPOSE[@]}" up -d --wait postgres redis s3 s3-init vault vault-init || return 1
  local rc=0
  IHSP_ENV_FILE=materials/dev.env uv run pytest -q -p no:cacheprovider || rc=$?
  "${COMPOSE[@]}" down -v
  return $rc
}
stage_openapi() {
  IHSP_ENV_FILE=materials/dev.env uv run python scripts/export_openapi.py || return 1
  git diff --exit-code -- openapi && test -z "$(git status --porcelain --untracked-files=all -- openapi)"
}
stage_security() { scripts/security_scan.sh; }

echo "CI (local) in $ROOT"
for s in "${STAGES[@]}"; do check "$s" "stage_$s"; done

echo
printf '%s\n' "${RESULTS[@]}"
[[ $FAILED -eq 0 ]] && echo "all stages passed" || echo "some stages failed (logs in reports/ci-local/)"
exit $FAILED

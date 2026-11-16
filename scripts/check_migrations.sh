#!/usr/bin/env bash
# Migration gate: heads load, upgrade heads from empty matches the ORM models, and the migrations new on
# this branch apply on a database that already has the older ones (the manual-migration rehearsal).
# Uses a throw-away database ihsp_migcheck_<pid> on the dev compose postgres, dropped at the end.
# Needs: docker compose -f materials/docker-compose.dev.yaml up -d --wait postgres
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export IHSP_ENV_FILE="${IHSP_ENV_FILE:-materials/dev.env}"
exec uv run python scripts/check_migrations.py

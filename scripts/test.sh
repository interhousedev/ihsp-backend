#!/usr/bin/env bash
# Run the tests with coverage: scripts/test.sh [pytest args]
set -euo pipefail
cd "$(dirname "$0")/.."
uv run pytest -q --cov=app --cov-report=term-missing "$@"

#!/usr/bin/env bash
# Formatting, imports, lint and types (CI runs this on every push).
set -euo pipefail
cd "$(dirname "$0")/.."
uv run black --check app tests
uv run isort --check-only app tests
uv run flake8 app tests
uv run mypy app

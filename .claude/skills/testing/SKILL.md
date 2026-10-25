---
name: testing
description: Use when writing or running tests in iht-backend - test-first bug fixes, choosing the layer (domain unit, application with fakes, HTTP, bot, models/migrations), the in-memory fakes in tests/fakes, requirement-ID docstrings, the alembic heads and models tests, the openapi export check, and targeted versus full runs against the Postgres dev compose services.
---

# Testing

Base rules are in CONTRIBUTING.md ("Tests first") and CODESTYLE.md.

## Loop

1. Name the rule in one sentence and find its requirement ID (`ACA-11`, `UF-STF-06`, `NB-14`).
2. List cases first: the normal path, each boundary and its neighbour, and one should-fail case per refusal (wrong owner, revoked access, over a limit, malformed input, duplicate, race).
3. Write the failing test at the **lowest layer** that shows it and see it fail:
   - `tests/<module>/unit`: domain and application with fakes; no services.
   - HTTP tests: status, error code and body shape of the route.
   - `tests/bot`: handlers with a fake bot.
   - `tests/models`: constraints, migrations, metadata.
   - `tests/integration`: real Postgres, Redis, S3, Vault.
4. Implement, run the module, then the full suite, then `scripts/style_check.sh`.

The docstring of every test starts with the IDs it covers: `"""ACA-11: a temporary mark shows in the journal grid."""`.

## Fakes

- Every port has an in-memory fake in `tests/fakes/<module>/`. A new port gets its fake in the same change; keep it behaviourally honest (ownership, uniqueness, ordering) so application tests mean something.
- Use the fake clock (`tests/fakes/clock.py`); never `sleep` or the wall clock. The school week is Monday to Friday.
- External services stay fake (EMIS, OpenRouter, Exa, Telegram). Real-model checks run only when the user asks.

## Database and migrations

- `tests/models/test_migrations.py` checks that `alembic upgrade heads` builds exactly the ORM models, that downgrade to base and upgrade again works, and that branches apply in any order. A new table or column without its migration fails here.
- Always `heads`, never `head`.

## Commands

```bash
uv run pytest tests/<module>/unit -q                                         # fast, no services
docker compose -f materials/docker-compose.dev.yaml up -d --wait postgres redis s3 s3-init vault vault-init
IHSP_ENV_FILE=materials/dev.env uv run pytest tests/<module> -q -p no:cacheprovider
IHSP_ENV_FILE=materials/dev.env uv run pytest -q -p no:cacheprovider         # full suite before a commit
IHSP_ENV_FILE=materials/dev.env uv run python scripts/export_openapi.py      # after any route or schema change
```

Tests need `materials/dev-keys/jwt-bearer.pem` (`scripts/dev.sh` creates it). `tests/deploy` needs Docker. Run one heavy suite at a time; the Docker VM has 8 GB.

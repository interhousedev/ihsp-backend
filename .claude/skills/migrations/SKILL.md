---
name: migrations
description: Use for DB table, column, constraint, index, enum, data or module schema changes and the migration gate; not for ad hoc queries
---

# Migrations

Details are in [migrations/README.md](../../../migrations/README.md).

## Rules

- Every module owns one PostgreSQL schema and one Alembic **branch** in `migrations/versions/<module>/`. Never read or write another module's tables.
- Always `alembic upgrade heads` (plural). There is no single head.
- **Never edit a revision that has been applied** anywhere (dev databases, CI, production). Write a new revision. Migrations are forward only in production.
- Data migrations are idempotent and batch large tables.

## New revision in an existing module

```bash
IHSP_ENV_FILE=materials/dev.env uv run alembic revision --autogenerate \
  --head <module>@head -m "<what changes>"
```

Review the generated file: schema names, server defaults, enum changes, index names. Autogenerate misses some changes (enum values, extension-backed types); write them by hand.

## New module

1. Create `migrations/versions/<module>/` and the first revision with `--branch-label <module>` and `--version-path`.
2. Add the folder to `version_locations` in `alembic.ini` (colon-separated list).
3. Add the schema to `SCHEMAS` in `migrations/env.py`, or autogenerate ignores it.
4. Import the module's ORM in the metadata the env loads.

## Migration gate (mandatory)

Any change touching the database (new table, column, constraint, index, enum value, check constraint, data migration) must pass `scripts/check_migrations.sh` before the work is reported done. It needs the dev compose postgres and does, on a throw-away database `ihsp_migcheck_<pid>`: `alembic heads` loads (no `op.*` call at module level; `op.f()` only inside `upgrade`/`downgrade`); `upgrade heads` from empty equals the ORM metadata (empty autogenerate diff); the **upgrade-on-existing-database rehearsal**: upgrade to every head minus the revisions new on this branch, then `upgrade heads` again. It is the `migrations` stage of `scripts/ci_local.sh`. A data migration also needs a test in `tests/models/test_migrations.py` with rows in place before the upgrade.

## Checks

`tests/models/test_migrations.py` must pass: upgrade heads builds exactly the models, downgrade base and upgrade again works, branches apply in any order. Add a test for any data migration.

---
name: migrations
description: Use when adding or changing database tables, columns, constraints, indexes or a whole module schema - Alembic with one branch per module under migrations/versions/<module>, version_locations in alembic.ini, SCHEMAS in migrations/env.py, upgrade heads, and the rule never to edit an applied revision.
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

## Checks

`tests/models/test_migrations.py` must pass: upgrade heads builds exactly the models, downgrade base and upgrade again works, branches apply in any order. Add a test for any data migration.

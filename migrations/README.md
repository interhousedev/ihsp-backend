# Migrations

Alembic with an async engine. **One Alembic branch per module**: the first revision of a
module has `branch_labels = ("<module>",)` and `down_revision = None`, and lives in
`migrations/versions/<module>/`. There are no foreign keys across schemas, so branches never
depend on each other. Schema `ai` is shared by the `ai` and `flashcards` branches.

Branches: `identity` (schema `id`), `academic`, `files`, `links`, `ai`, `flashcards` (tables in
schema `ai`), `notify`, `admin`, `mail`, `lms`, `notebooks`, `library`, `vectors` (schema `vectors`: the
shared `embeddings` table; needs the `pgvector` Postgres image).

## Rules

- Revision ids are fixed: `<module>_0001`, `<module>_0002`, ... (`alembic_version.version_num` is
  `VARCHAR(32)`, keep ids short).
- The first revision runs `CREATE SCHEMA IF NOT EXISTS <schema>` (the version table lives in
  `public`). The `academic` first revision also runs `CREATE EXTENSION IF NOT EXISTS btree_gist`.
  The `vectors` one runs `CREATE EXTENSION IF NOT EXISTS vector` (downgrade keeps it) and creates the
  `halfvec(1024)` column and its HNSW index with plain SQL/`op.create_index`. The `notebooks` one runs `CREATE EXTENSION IF NOT EXISTS pg_trgm` (its downgrade leaves the
  extension in place) and creates `passages.search_vector` as a stored generated column
  (`sa.Computed`).
- Write revisions against an empty throw-away database. Never autogenerate against a
  shared database. Never edit an applied revision.
- Exclusion constraints: `op.create_exclude_constraint(..., (sa.literal_column("room_id"), "="), ...)`,
  never `sa.text`. `postgresql_nulls_not_distinct=True` is fine (PostgreSQL 16).
- Always use `alembic upgrade heads` (plural); `head` fails with several branches. The CLI
  `python -m app migrate` does exactly that.
- `env.py` reads the URL from `sqlalchemy.url` (if set by code), else from the app settings
  (`IHSP_DATABASE__URL`). Tests can pass `config.attributes["connection"]` (a sync connection from
  `await conn.run_sync(...)`), because `asyncio.run` cannot nest in a running loop.

## First revision of a module

```bash
uv run alembic -x schema=<schema> revision --autogenerate --head=base \
  --branch-label=<module> --version-path=migrations/versions/<module> \
  --rev-id=<module>_0001 -m "<module> init"
```

Then add `op.execute("CREATE SCHEMA IF NOT EXISTS <schema>")` as the first statement, check that
GIN, partial, exclusion and CHECK constraints were rendered (add them by hand when they were
not), and write `downgrade()`.

`-x schema=<schema>` limits autogenerate to that schema's objects. Autogenerate refuses a
database that is not at the heads, so on the throw-away database run `alembic upgrade heads`
first (before the new branch exists).

## Later revisions

```bash
uv run alembic revision --autogenerate --head=<module>@head -m "<what changed>" --rev-id=<module>_0002
```

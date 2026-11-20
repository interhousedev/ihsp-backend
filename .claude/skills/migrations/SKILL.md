---
name: migrations
description: Use for schema changes (tables, columns, constraints, indexes, enums), data backfills, seeds and imports, and the server-to-server copy checks. Not for ad hoc queries.
---

# Migrations

## When to run this

- Run it when the user asks for it, and whenever a change lands that touches data: a table, column, constraint, index, enum value, seed, import or backfill.
- Before a server-to-server copy (`scripts/migrate_runner.sh` on the old server, `scripts/migrate_target.sh` on the new one), check the data on both sides.

## Per-change checks

1. Write the model change and the Alembic revision under `migrations/versions/<module>/`. Use the module's branch. Never edit an applied migration.
2. Run `scripts/check_migrations.sh`. It needs the dev postgres (`docker compose -f materials/docker-compose.dev.yaml up -d --wait postgres`). It checks: a single head per branch, an empty upgrade that matches the models, and an upgrade on an existing database.
3. The upgrade-on-existing-database rehearsal is mandatory. Downgrade is not required.
4. Data backfills must be idempotent: running them twice changes nothing.
5. `ci_local.sh` runs the migrations stage. It fails when postgres is unreachable. `--allow-skip` is for local work only, never for a release.

## Server-to-server copy checks

- `migrate_runner.sh` (old server) stops the worker, scheduler, bot and mail, dumps Postgres, snapshots Redis, copies objects, config, Vault and backups, then counts every store (`scripts/migration_counts.sh` writes `counts.tsv`) and transfers.
- `migrate_target.sh finish` (new server) checks the checksums and `counts.tsv`, restores, then runs `verify_restore`. It prints a table of every store (ihsp, hydra, bugsink, redis, s3, vault seal state, alembic `heads` and `current`) with source and target values.
- Any mismatch exits 4 and leaves no `RESTORED` marker. Do not start the stack; fix the cause or run `abort`.
- Counts are taken while the source is quiet. If the API was still writing, a mismatch can be live traffic, not corruption. Stop the stack first and count again.
- Vault is compared by its seal state, not by row count. Unseal it with the old server's keys.

## Checklist

- [ ] Revision added under `migrations/versions/<module>/`; models match.
- [ ] `scripts/check_migrations.sh` passes, including the upgrade on an existing database.
- [ ] Backfills and seeds are idempotent.
- [ ] `ci_local.sh migrations` ran without `--allow-skip`.
- [ ] For a copy: `counts.tsv` present, and `verify_restore` printed only `ok` rows.
- [ ] No applied migration edited; no secret printed or committed.

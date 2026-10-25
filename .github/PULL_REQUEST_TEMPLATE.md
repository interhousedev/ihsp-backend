<!-- Title: a Conventional Commit, e.g. `fix(academic): keep temporary marks in the journal grid`. -->

## What and why

<!-- What changes and why. Requirement IDs (ACA-11, NB-14, ...). Link the issue: Fixes #123. -->

## How it was tested

<!-- Tests added, commands you ran, manual checks (bot, web app). -->

## Checklist

- [ ] Tests written first; docstrings name the requirement IDs; `uv run pytest` passes for the touched modules and the full suite is green in CI
- [ ] `scripts/style_check.sh` passes (black, isort, flake8, mypy)
- [ ] Migrations: new revision in the module's branch, `alembic upgrade heads` works, no applied revision edited
- [ ] API: `openapi/openapi.json` exported and committed; breaking changes for `iht-web` described below
- [ ] User-facing text in uz, ru and en (ПК/ИК terms, Uzbek `ʼ`)
- [ ] README.md, CODESTYLE.md, SECURITY.md or `materials/.env.sample` updated when behaviour, rules, a trust boundary or a setting changed
- [ ] No secrets, real student data or dumps in the diff

## Breaking changes

<!-- None, or what breaks and how to migrate. -->

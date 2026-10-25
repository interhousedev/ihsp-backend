# Contributing to IHSP

Thank you for helping the students and staff of International House Tashkent. This page explains how to set up, how to change the code and how to get a pull request merged.

## Ground rules

- Be kind; the [Code of Conduct](CODE_OF_CONDUCT.md) applies everywhere.
- Report vulnerabilities privately ([SECURITY.md](SECURITY.md)), never in an issue.
- Open an issue before a large change so we can agree on the approach first.
- Never commit secrets, real student data or production dumps. Fake modes need no keys.
- The coding rules are in [CODESTYLE.md](CODESTYLE.md); read them once before your first pull request.

## Setup

You need Docker 28+ with compose v2, [uv](https://docs.astral.sh/uv/) (it installs Python 3.13) and `libmagic` (`brew install libmagic` on macOS).

```bash
uv sync --frozen
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out materials/dev-keys/jwt-bearer.pem  # or let scripts/dev.sh do it
docker compose -f materials/docker-compose.dev.yaml up -d --wait postgres redis s3 s3-init vault vault-init
scripts/dev.sh all
```

The full stack in Docker (with the web apps from a sibling `iht-web` checkout) is `scripts/local_up.sh`; see [README.md](README.md#local-development).

## Tests first

1. Name the rule you are adding or fixing in one sentence and find its requirement ID (`ACA-11`, `NB-14`, ...).
2. Write the failing test at the lowest layer that shows it: domain unit test, application test with the in-memory fakes from `tests/fakes/`, HTTP test, or a model/migration test. The docstring starts with the requirement IDs.
3. Make it pass, then run the module, then everything:

```bash
uv run pytest tests/<module>/unit -q                                        # no services needed
IHSP_ENV_FILE=materials/dev.env uv run pytest tests/<module> -q -p no:cacheprovider
IHSP_ENV_FILE=materials/dev.env uv run pytest -q -p no:cacheprovider        # full suite, needs the dev compose services
scripts/style_check.sh                                                      # black, isort, flake8, mypy
```

A bug fix starts with a test that reproduces the bug.

## Style

black (line length 88), isort and flake8, mypy in strict mode. Do not use ruff format. `scripts/style_check.sh` must pass; CI runs the same checks.

## Database migrations

One Alembic branch per module under `migrations/versions/<module>/`. Generate a revision in the module's branch, run `alembic upgrade heads` (plural), and never edit a revision that has been applied anywhere. See [migrations/README.md](migrations/README.md).

## API contract

`openapi/openapi.json` is the contract with the web apps. If you change a route or a schema:

```bash
IHSP_ENV_FILE=materials/dev.env uv run python scripts/export_openapi.py
```

Commit the exported file in the same pull request; CI fails when it is stale. Removing or renaming a field breaks `iht-web`: say so in the pull request, and after the merge run `bun run sync:openapi` in `iht-web`.

## User-facing text

Every string exists in Uzbek, Russian and English (`locales/uz|ru|en`). Use the terms "Промежуточный контроль (ПК)" and "Итоговый контроль (ИК)", and the modifier letter apostrophe `ʼ` (U+02BC) in Uzbek (`oʼquvchi`, `gʻ`).

## Commits

[Conventional Commits](https://www.conventionalcommits.org/) with a scope, lowercase imperative:

```
feat(academic): save absent list with audience snapshot
fix(bot): keep the journal open after the lesson day
```

Scopes are module or interface names (`academic`, `notebooks`, `bot`, `identity`, `ci`, `docs`, ...). Name the requirement IDs in the body. One commit per feature or fix; never one mega commit. Mention `contract export` in the subject when the commit changes `openapi.json`.

## Pull requests

- Fill in the template; link the issue (`Fixes #123`).
- Keep it focused. Tests, style checks and the OpenAPI check must be green.
- Update README.md, CODESTYLE.md, SECURITY.md or `materials/.env.sample` when behaviour, rules, a trust boundary or a setting changes.
- A maintainer from [CODEOWNERS](.github/CODEOWNERS) reviews it. We squash or rebase; keep the commit history readable.

## Coding agents

Agents follow [CLAUDE.md](CLAUDE.md) and the project skills in [`.claude/skills/`](.claude/skills). The same rules apply to their output: tests first, layered commits, no secrets.

## License

By contributing you agree that your contribution is licensed under the project's [LICENSE](LICENSE).

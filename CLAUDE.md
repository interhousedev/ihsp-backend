# CLAUDE.md (iht-backend)

Instructions for Claude Code working in this repository. Read [README.md](README.md) for the architecture, local development and deployment, and [CODESTYLE.md](CODESTYLE.md) for the coding rules. This file does not repeat them.

## What this is

The Python backend of the IHT lyceum platform (internal name IHSP): FastAPI, aiogram, SQLAlchemy 2 async, Alembic, taskiq, one image with several processes. The web apps are in the sibling repository `iht-web`; the two meet at `openapi/openapi.json`. The product serves students, teachers, administrators, librarians and course staff of the Academic Lyceum International House Tashkent. The school week is Monday to Friday.

## Where things live

- `app/modules/<name>/{domain,ports,application,infrastructure,wiring.py}`: business logic. Modules: academic, admin, ai, certificates, dashboard, files, flashcards, identity, knowledge, library, links, lms, mail, notebooks, notify, vectors.
- `app/interfaces/{http,bot,mcp,smtp,jobs}`: protocol edges. `app/bootstrap/`: one composition root per process. `app/shared/`: kernel and cross-module contracts.
- `app/settings*.py`: settings (`IHSP_*`). `materials/.env.sample` documents them.
- `app/shared/ai_tasks.py`: every model call site is a named AI task. `app/modules/notebooks/domain/artifacts/strict.py`: structured-output helpers (`NOT_NULL`).
- `migrations/versions/<module>/`: one Alembic branch per module.
- `materials/`: compose files, nginx, Hydra, Vault. `scripts/`: dev, local stack, deployment, backup, export and smoke scripts.
- `tests/fakes/`: in-memory fakes of every port. `tests/deploy/`: deployment checks.

## Commands

```bash
uv sync --frozen
scripts/style_check.sh                                     # black, isort, flake8, mypy
IHSP_ENV_FILE=materials/dev.env uv run pytest -q -p no:cacheprovider        # needs the dev compose services
uv run pytest tests/<module>/unit -q                       # unit tests, no services
docker compose -f materials/docker-compose.dev.yaml up -d --wait postgres redis s3 s3-init vault vault-init
IHSP_ENV_FILE=materials/dev.env uv run python scripts/export_openapi.py     # after any route or schema change
```

The formatter is black (line length 88) with isort and flake8; do not use ruff format. The tests need `materials/dev-keys/jwt-bearer.pem`, which is git-ignored; `scripts/dev.sh` creates it, or run `openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out materials/dev-keys/jwt-bearer.pem`. `tests/deploy` needs Docker.

## API contract workflow

Changing a route or a schema means: export `openapi/openapi.json`, commit it with the change, and tell the user that `iht-web` needs `bun run sync:openapi` (it reads `${IHSP_BACKEND_DIR:-../iht-backend}/openapi/openapi.json`). CI fails when the committed document is stale. Keep the web repository in mind: removing or renaming a field is a breaking change for it.

## Working rules

- **Use parallel subagents.** Work fast: split independent work among parallel Sonnet subagents (about 7 to 10 at most), each with a precise, self-contained task and its own set of files.
- **Layered commits.** One commit per feature or fix, never one mega commit. Subagents never run git; the coordinator commits. If signing fails (1Password), commit with `git -c commit.gpgsign=false commit ...`.
- **Keep memory safe.** Docker VMs are small (8 GB). Never `docker build` the web image the long way while tests run. Do not run many heavy processes at once; background helpers such as memory-hungry summarizers must be watched.
- **Never print or commit secrets.** The OpenRouter and Exa keys exist only in git-ignored files (`materials/dev-keys/secrets.env`, `.env.local`, `.env.prod`). `materials/dev.env` keeps `IHSP_OPENROUTER__API_KEY=` empty and the mode `fake`. The four public dev placeholders in `materials/.env.sample` stay.
- **UniLibrary.** `api.unilibrary.uz` rejects a foreign `Origin` with 403. Never spoof `Origin` or `Referer`; the honest client sends its own `User-Agent` and no `Origin`/`Referer`. A 403 is a failure that opens the breaker. The flag `LIBRARY__UNILIBRARY_ENABLED` stays off until the operator agrees in writing.
- **Copy.** All user-facing text exists in uz, ru and en. The terms are "Промежуточный контроль (ПК)" and "Итоговый контроль (ИК)"; never "Рубежный контроль".
- **Structured-output JSON schemas** may have at most 16 union or nullable parameters (Anthropic answers HTTP 400 otherwise). Use `NOT_NULL` from `app/modules/notebooks/domain/artifacts/strict.py`; `to_strict_schema()` makes every property required and adds `additionalProperties: false`; avoid recursive schemas.
- **Edge cases of Python tooling.** Use `uuid_utils.compat.uuid7`, not `uuid_utils.uuid7`. Always `alembic upgrade heads`. Never edit an applied migration.

## AI models and limits

- Each call site is a named task. Default model `anthropic/claude-haiku-5.5` with reasoning `none` for chats, notebooks and Studio; the smart tier is `google/gemini-3.8-flash` (reasoning `low`, a soft weekly request limit); embeddings use `qwen/qwen3-embedding-4b`. Per-task overrides are `IHSP_AI__TASKS__<TASK>__<FIELD>`.
- AI limits are soft values. The environment gives the defaults; administrators change them at runtime on the admin "Limits & usage" page, for everyone or per user, and the change applies within 30 seconds. Staff are unlimited but every model call is recorded in the usage ledger.
- Web search uses Exa with a limiter of 10 requests per second shared by all processes (`IHSP_EXA__MAX_QPS`). Stored pages are searched first.
- Fake modes (the default) need no key. Run real-service checks only when the user asks, with keys from the git-ignored files.

## Deployment notes

The server only pulls images built by CI. `scripts/cloud_deploy.sh <host> --tag <version>` deploys and rolls back; migrations are forward only. Vault starts sealed after a reboot. Never put `.env.prod`, `secrets/` or the Vault unseal keys into git, chat or logs.

## Documentation policy

The only Markdown files are `README.md` files, `CODESTYLE.md` and this file. Do not add design documents, plans or reports to the repository; put such text in the conversation or in the pull request. Update README.md or CODESTYLE.md when behaviour or rules change.

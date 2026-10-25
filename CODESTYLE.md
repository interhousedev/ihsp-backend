# Code style (backend)

How we write backend code. It follows the conventions of the 21ID bot and Auth API, plus test-driven development and a domain-driven structure. When this file and old code disagree, this file wins.

## Principles

1. **Tests first.** No production code without a failing test that needs it. Bug fixes start with a test that reproduces the bug.
2. **One file per logical function.** One use case, one HTTP handler, one bot handler, one keyboard per file. The file name says what it does: `submit_attendance.py`.
3. **Folders are the architecture.** Code is grouped by module (business area), then by layer.
4. **Domain first.** Business rules live in plain domain code with no framework, database or network imports. Frameworks are details at the edges.
5. **Explicit dependencies.** Objects get what they need through their constructor. Each process has one composition root that builds a `Container`. No globals, no service locators, no import-time side effects, except registering handlers on a module-level `router`.
6. **Types everywhere.** `mypy --strict`. No `Any` without a comment that says why.
7. **Small and boring.** Cyclomatic complexity at most 8 (`max-complexity = 8`). Clear code over clever code; a few lines of duplication over a wrong abstraction.
8. **Errors are part of the design.** Expected failures are typed errors with a message for the user and details for support. Nothing is swallowed silently.
9. **Requirement IDs connect everything.** Tests, commits and pull requests name the requirement or flow they cover (`ACA-11`, `UF-STF-06`, `NB-14`). A test docstring starts with the IDs it covers.

## Tooling

| Tool | Setting |
|---|---|
| Python | 3.13 |
| Formatter | `black`, line length 88. Not ruff format |
| Imports | `isort`, black profile, sections stdlib, app (first party), third party, local |
| Lint | `flake8` with `select = E,F,W,B,C4,C90,ANN,D,N,RET`, `max-complexity = 8`, Google docstrings (`flake8-annotations`, `-bugbear`, `-docstrings`, `-return`, `-comprehensions`, `pep8-naming`) |
| Types | `mypy --strict` on `app` |
| Tests | `pytest`, `pytest-asyncio` (`asyncio_mode = "auto"`, session loop scopes), `pytest-cov`, `hypothesis`, `testcontainers`, `respx` |

`scripts/style_check.sh` runs black, isort, flake8 and mypy; CI runs the same on every push.

## Module and layer structure

Every module under `app/modules/<name>/` has the same layers. Dependencies point inwards only.

```
interfaces (http, bot, mcp, jobs)  ->  application  ->  domain
                                          |
                                        ports  <-  infrastructure
```

- `domain/`: entities, value objects, policies. No framework, database or network imports.
- `ports/`: `Protocol` classes for repositories, units of work and gateways. Never inherit concrete infrastructure.
- `application/`: use cases, one class per file (`PublishCourse`, `LinkTelegram`), taking ports in the constructor and exposing `execute`.
- `infrastructure/`: SQLAlchemy models and repositories, S3, Vault, EMIS and OpenRouter adapters.
- `wiring.py`: builds the module's sub-container (`container.academic.submit_attendance`).
- `app/interfaces/`: HTTP routers, the aiogram bot, MCP servers, SMTP, job wrappers. They translate a protocol event into one use case call and nothing else.
- `app/shared/`: the kernel and cross-module contracts (`shared/contracts/`), `Clock`, ids, `Actor`, `BaseError`, i18n, database helpers.

A module never reads another module's tables and never imports another module's internals; it uses the contracts in `app/shared/contracts/`. There is one bootstrap per process in `app/bootstrap/`; a process builds only what it needs and gets only the credentials it needs (only `identity` and `worker` build the Vault client).

## Naming

| Thing | Style | Example |
|---|---|---|
| modules, files, functions, variables | snake_case | `submit_attendance.py` |
| classes | PascalCase | `Lesson`, `SubmitAttendance` |
| use cases | verb and noun | `PublishCourse` |
| repositories, gateways | noun and role | `LessonRepository`, `EmisGateway` |
| external API models | `...DTO` | `RatingsV1DTO` |
| HTTP schemas | `...Body` / `...Response` | `SubmitAttendanceBody` |
| errors | `...Error` | `AttendanceWindowClosedError` |
| constants | UPPER_SNAKE_CASE | `OTP_TTL = timedelta(minutes=5)` |
| bot and message i18n keys | kebab-case `area-screen-thing` | `attendance-submitted` |

## Docstrings and comments

Every public module member has a one-line Google-style docstring that ends with a period. Add `Args:`, `Returns:` and `Raises:` only when they say something the signature does not. Comments explain why, not what. Long files may use separators such as `# - - - Repositories - - -`.

## Data and types

- Domain entities are pydantic v2 models or `@dataclass(slots=True)`; value objects are frozen.
- Time and random defaults come from factories (`Field(default_factory=...)`), never `Field(default=datetime.now())`.
- Datetimes are timezone-aware UTC and come from an injected `Clock`; convert to `Asia/Tashkent` only at the edges.
- IDs are `uuid.UUID` (UUIDv7 from `shared.ids`; use `uuid_utils.compat.uuid7`, not `uuid_utils.uuid7`), never `str` inside code.
- Enums are `StrEnum`.

## Configuration and secrets

Each process reads a `Settings` object (pydantic-settings, `IHSP_*` variables) validated at startup. No `os.getenv` in code. Constructors take typed, non-optional dependencies. `materials/.env.sample` documents every variable. Secrets come from the environment or Vault and live only in git-ignored files (`.env.local`, `.env.prod`, `secrets/`, `materials/dev-keys/`). Production code paths never import fakes.

## Errors

- Domain errors subclass `BaseError` with a stable `code` (`attendance/window-closed`, also the problem+json `type`), a `client_message` that is an i18n key with parameters (not free text, no personal contacts), `support_details` for logs and admins, and `notify_user`.
- Each interface maps errors once: FastAPI exception handlers produce `application/problem+json`, the aiogram `ErrorMiddleware` shows the user message and reports to the admin with an error UUID, job wrappers log and retry.
- Never `except:` and never `except Exception: pass`; catch the narrowest type. Never `print`; use `structlog` with context (`request_id`, `user_id`, `error_id`).

## Async

All I/O is async. Blocking libraries (`hvac`, PDF parsing, argon2) run in `asyncio.to_thread`. Limit concurrency with `asyncio.Semaphore` or a queue; never an unbounded `gather` over user data. External calls have timeouts and, where safe, retries with backoff.

## FastAPI

- One handler per file, calling exactly one use case. Layout: `app/interfaces/http/v1/<area>/<feature>/{router.py,schemas.py,handlers/}`.
- Routes are versioned `/v1` and grouped by platform (`id`, `me`, `staff`, `admin`, `lms`, `files`, `links`, `ai`).
- Explicit Pydantic request and response schemas; never return ORM objects or domain entities.
- Errors are `application/problem+json` with a stable `type`. Lists use cursor pagination (`?cursor=&limit=`).
- OpenAPI is the contract with iht-web. Changing it is a reviewed change; export it and commit `openapi/openapi.json` in the same pull request.

## aiogram bot

- Buttons for every action; users never have to reply to a message or know a gesture.
- Callback data carries the action and entity IDs in a `CallbackData` class with a short prefix. Telegram allows 64 bytes, so UUIDs are packed as 22-character base64url and list items are referenced by position. Every `CallbackData` class has a test that packs its largest value and asserts at most 64 bytes.
- Handlers re-read state from the use case and edit the message they were pressed on. Never store Telegram message IDs in domain data.
- No hard-coded texts: every text and button label is an i18n key; keyboards are built by `keyboards/<name>.py:get(i18n, ...)`.
- Every multi-step input has Cancel, and FSM states expire after one hour.
- Handlers only translate Telegram events into use case calls; no SQL, no business rules.
- Filters and middlewares are registered on routers in `register_filters()`; routers are collected in `register_sub_routers()`.

## Database and migrations

- SQLAlchemy 2.0 typed ORM (`Mapped[...]`), async with asyncpg. ORM models live in `infrastructure/orm/`, separate from domain entities; repositories map between them. Relationships use `lazy="raise"`.
- One schema per module. Table names are plural snake_case. Constraint names follow the metadata naming convention (`pk_`, `fk_`, `uq_`, `ix_`, `ck_`).
- Transactions are opened by the application layer (a unit of work), never by repositories. Rows edited concurrently carry a `lock_version`; a conflict is a typed error. `jsonb` columns have a Pydantic schema in the domain.
- Alembic uses one branch per module: the first revision has `branch_labels = ("<module>",)` and `down_revision = None` and lives in `migrations/versions/<module>/`. Revision ids are `<module>_0001`, `<module>_0002`, and so on (the version column is 32 characters). Always pass `schema=` to `op.*`. Foreign keys exist only inside a schema.
- Write revisions against an empty throw-away database; never autogenerate against a shared one. Never edit an applied revision. Every revision has a working `downgrade()`; CI-style tests run upgrade, downgrade, upgrade. Always `alembic upgrade heads` (plural).
- See `migrations/README.md` for the commands that create the first and later revisions.

## Tests

| Level | What | Tools |
|---|---|---|
| Domain unit | entities, value objects, policies | `pytest`, `hypothesis`; milliseconds, no I/O |
| Use case | application services with fake repositories and gateways | `pytest-asyncio`, fakes from `tests/fakes/` |
| Integration | repositories, migrations, S3, Redis, Vault, EMIS client | real services from the dev compose, `respx` for EMIS |
| HTTP | routes, auth, validation, error mapping | `httpx.AsyncClient` with `ASGITransport` |
| Bot | handlers, keyboards, callback data, FSM | updates fed to the dispatcher with a fake bot session |
| Deploy | Dockerfiles, nginx, compose, scripts | `tests/deploy` |

- Test behaviour, not implementation. One behaviour per test, named as a sentence (`test_absent_list_is_saved_with_audience_snapshot`). Arrange, act and assert are separated by blank lines. Factories (`make_lesson(...)`) instead of big fixtures.
- Fakes for our ports (repositories, `EmisGateway`, `FileStorage`, `LlmGateway`, `TelegramSender`, Hydra admin, the LLM); real adapters only in integration tests. `unittest.mock` is a last resort, for things with no port such as the aiogram bot session.
- Time and randomness are injected (`Clock`, `IdGenerator`, `Random`).
- Coverage gate: 90 percent for `domain` and `application` (`coverage report --include="app/modules/*/domain/*,app/modules/*/application/*" --fail-under=90`), 80 percent overall. Coverage is a floor, not a goal.
- `httpx.ASGITransport` runs no lifespan; use `app.state` or `app.router.lifespan_context(app)`. A `@given` test with a function-scoped DB fixture needs the fixture widened or the health check suppressed.

## Internationalization

All user-facing text exists in `uz`, `ru` and `en` (`locales/`). Add all three at once. Error messages are i18n keys, never free text. Midterm control is "Промежуточный контроль (ПК)" and final control is "Итоговый контроль (ИК)"; never "Рубежный контроль".

## Git

- Conventional Commits with a scope, lowercase imperative: `feat(academic): save absent list with audience snapshot`. Name the requirement IDs in the body.
- Layered commits: one per feature or fix, never one mega commit.
- Pull requests carry their tests, pass CI and name the requirement IDs.

## Definition of done

- [ ] Tests written first and passing; coverage gates met.
- [ ] `scripts/style_check.sh` is clean.
- [ ] Migrations upgrade and downgrade.
- [ ] i18n keys exist in all three languages.
- [ ] `openapi/openapi.json` is re-exported when a route or schema changed.
- [ ] No secrets, no `print`, no TODO without an issue link.

---
name: release
description: Use for CI runs, backend image builds/pushes, CHANGELOG.md updates, and tagging iht-backend releases
---

# Release

Backend and web release together under the same version. Do the same steps in `iht-web` (see its `release` skill). Commit, push, tag and deploy only when the user asks.

## 1. Run CI locally

```bash
scripts/ci_local.sh --fast      # lint (with mypy and ty), unit, openapi: before every push
scripts/ci_local.sh             # lint, test, openapi, security: before a release
scripts/ci_local.sh test        # one stage
scripts/security_scan.sh semgrep
```

Logs are in `reports/ci-local/`. The GitHub Test workflow runs on pull requests and on pushes to `main`. Still run the `test` stage on the commit you will release.

For prompt changes, run the real-model evals when the user asks (see the `testing` skill and `tests/ai/evals/conftest.py`). Each run costs about 150 model calls.

## 2. Update the changelog

Move the entries from `[Unreleased]` in `CHANGELOG.md` to `## [X.Y.Z] - YYYY-MM-DD`, adding anything missing from `git log <last tag>..HEAD`. Write for readers, not commit by commit. List known issues. Commit it with the release, before the tag.

Also bring the GitHub Pages docs (`docs/*.md`, `mkdocs.yml` nav) up to date with what the release changed (new routes, scopes, settings, features), then check the site:

```bash
uv sync --only-group docs --frozen
uv run mkdocs build --strict      # what the Docs workflow runs; must pass before the tag
```

The Docs workflow publishes the site on the push to `main` that touches `docs/**`, `mkdocs.yml`, `pyproject.toml` or `uv.lock`; confirm that run too.

When `pyproject.toml` or `uv.lock` changed, also commit `licenses/python.json`. When a route or schema changed, also commit `openapi/openapi.json`.

## 3. Push and wait for CI

Commit in layers, signed, then push `main`. Wait until Test, Security, Lint, CodeQL, Docs and Build image pass on that commit (`gh run list -c <sha>`).

## 4. Tag

```bash
git tag -s vX.Y.Z -m vX.Y.Z <sha>
git push origin vX.Y.Z
```

Use a new version for every release. Published images are already in use, so move a tag only when the user explicitly asks.

The tag starts Build image, which scans with Trivy and publishes `X.Y.Z`, `X.Y`, `latest` and `sha-<commit>` to `ghcr.io/interhousedev/ihsp-backend`. Confirm that the run on the tag succeeded.

## 5. Deploy

```bash
scripts/cloud_deploy.sh <ssh-host> --tag X.Y.Z
```

The server only pulls images. Migrations are forward only, so rolling back the app does not undo them.

## Build an image by hand

Only when CI cannot do it. Needs `docker login ghcr.io` with write access.

```bash
scripts/image_push.sh X.Y.Z --arch amd64     # add --load to keep it local
```

## When a push is denied

`denied: permission_denied` on GHCR means the repository lacks access to the package. An organization owner opens the package settings, then **Manage Actions access**, and gives the repository the **Write** role. There is no API for this setting.

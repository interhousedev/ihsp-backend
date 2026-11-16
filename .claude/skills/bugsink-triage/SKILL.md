---
name: bugsink-triage
description: Use for Bugsink IHSP-BACKEND errors: fetch, trace prod logs, reproduce, fix, resolve.
---

# Bugsink triage

`scripts/bugsink.py` talks to the Bugsink canonical API. Set `IHSP_BUGSINK_URL` and `IHSP_BUGSINK_TOKEN` (a token with `issues:read`, `events:read`, `issues:triage`; optionally `IHSP_BUGSINK_PROJECT`) in a git-ignored file. Never print or commit the token.

## Workflow

1. **List**: `uv run python scripts/bugsink.py list` shows open issues (id, event count, last seen, title).
2. **Fetch**: `scripts/bugsink.py show <issue-id>` prints the issue and its latest event: stacktrace, tags, request. Note the `error_id` or request id and the timestamp.
3. **Prod logs**: `ssh root@46.225.36.78 'cd /opt/ihsp && docker compose logs --since 24h api | grep <error_id or request id>'` (try the worker or bot service for jobs and bot errors). Read only; do not change prod.
4. **Classify**: an upstream outage (EMIS, UniLibrary, model provider) is not our bug: it must log at warning and answer problem+json 503 with `Retry-After`; do not "fix" it, fix the log level. Real defects continue.
5. **Reproduce** with a failing test first (see the `testing` skill), then fix.
6. **Resolve after deploy**: once the fixed version is running, `scripts/bugsink.py resolve <issue-id>`. A recurrence reopens it.

---
name: api-contract
description: Use when adding, removing or changing an HTTP route, a request or response schema, an error code or a query parameter in app/interfaces/http - exporting openapi/openapi.json, the CI staleness check, and the iht-web sync and breaking-change rules.
---

# API contract

`openapi/openapi.json` is the contract with `iht-web` (it reads `${IHSP_BACKEND_DIR:-../iht-backend}/openapi/openapi.json`).

## Every route or schema change

```bash
IHSP_ENV_FILE=materials/dev.env uv run python scripts/export_openapi.py
```

1. Commit `openapi/openapi.json` **in the same commit** as the change; say "contract export" in the subject.
2. CI (`test.yml`) fails when the committed file differs from the export.
3. Tell the user that `iht-web` needs `bun run sync:openapi` (regenerates the typed client) and a commit there.

## Compatibility

- Adding an optional field or a new route is safe.
- Removing or renaming a field, changing a type, making a field required in a request, or changing an error code **breaks iht-web**. Avoid it; if needed, add the new shape first, migrate the web, then remove the old one in a later release, and mark it breaking in the PR.
- Schemas: explicit pydantic models with `operation_id`, tags and documented error responses; stable machine error codes, translated messages.
- Never put secrets, internal ids of other users or debug fields into a response schema.

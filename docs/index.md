# Platform API guides

Guides for the integrations the platform backend exposes over HTTP.

- [Personal tokens](personal-tokens.md): long-lived tokens for scripts and AI clients that act on your own account (`/v1/me/*`).
- [Entrance devices](entrance-devices.md): face-recognition devices at the school door, created by administrators.

The full contract of every route is the OpenAPI document, `openapi/openapi.json` in the repository. Errors are `application/problem+json` with a stable `code`.

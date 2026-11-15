# Platform API guides

Guides for the integrations the platform backend exposes over HTTP.

- [Personal tokens](personal-tokens.md): long-lived tokens for scripts and AI clients that act on your own account (`/v1/me/*`).
- [Telegram bots](telegram-bots.md): the bot registry, per-bot features, webhooks and notifications.
- [Entrance devices](entrance-devices.md): face-recognition devices at the school door, created by administrators.
- [LMS access rules](lms-access.md): restricting courses and lessons to signed-in users, students or chosen groups and users.
- [MCP servers](mcp.md): connecting AI apps, scopes and the newest tools.

The full contract of every route is the OpenAPI document, `openapi/openapi.json` in the repository. Errors are `application/problem+json` with a stable `code`.

# MCP servers

The backend runs MCP servers (students, teachers, LMS, administration and the combined `/mcp/app` connector) for AI apps such as ChatGPT and Claude. A person connects an app through IHT ID (OAuth 2.0 with PKCE) and picks scopes on the consent screen; the connectors page of IHT ID lists calls (kept 90 days), open scope offers and media links. The full tool list per server is in the repository README, section "MCP servers"; the trust rules are in `SECURITY.md`.

## New in release `2026-12-mcp-2`

| Tool | Server | Scope |
|---|---|---|
| `get_my_group` | students | `group:read` (blocked members are skipped) |
| `get_rating_book` | students | `rating_book:read` |
| `list_notifications` | students, teachers | `notifications:read` |
| `set_access` | LMS | course editing scopes; see [LMS access rules](lms-access.md) |

Existing connections keep their grants: a new scope is offered on the connectors page and is used only after the person accepts it. Names, contacts and notification links returned by these tools are marked as untrusted text for the model.

The operator adds the new scopes to the Hydra clients (`group:read`, `rating_book:read`, `notifications:read`) when deploying.

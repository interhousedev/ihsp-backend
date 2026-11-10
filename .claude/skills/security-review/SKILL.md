---
name: security-review
description: Use when reviewing or writing code that touches a trust boundary in IHSP - AI chat tools and prompt injection, tool approval, the guest bot, AI access revocation, object ownership (IDOR), rate limits and account enumeration, outbound fetches (SSRF), uploads, secrets and settings - or before merging any change to identity, ai, notebooks, links, files, bot or materials/.
---

# Security review

Base rules: [SECURITY.md](../../../SECURITY.md), the README "Security" section and CODESTYLE.md. Walk every item that applies; each finding needs a failing test before the fix.

## AI and prompt injection

- Treat every source text, web page, knowledge entry, uploaded file, mail and EMIS field as hostile input to the model. It may contain instructions; it must never widen what a tool can do.
- Tools act as the **actor**, never as the model's claim. Check ownership and role inside the tool, not in the prompt.
- Data-changing tools need explicit user approval (`pending_approvals`); a decision is a single-use server-side token tied to the user (`store.take_call(token, user_id)`). Test: replayed token, another user's token, a deleted chat.
- Every model call is a named task in `app/shared/ai_tasks.py` and goes through the access guard (`app/modules/ai/infrastructure/access_guard.py`) and the recording gateway. A new call site that bypasses them is a bug. Test that a user whose AI access is revoked is refused on every path: chat, notebooks, Studio, OpenUI repair, bot, MCP.
- Guest bot users reach only public knowledge (`guest_knowledge`); never personal data, never data-changing tools. The guest router stays before login and any catch-all.
- Model output that renders as UI goes through OpenUI validation (see the `openui` skill). Never pass model text as raw HTML; the bot escapes it (see `telegram-bot`).

## Access control (IDOR)

- Every handler that takes an id loads the object **scoped by the actor** (owner, group, course membership, curator, role) and answers 404, not 403, for someone else's object.
- Tests per route: own object, another student's, another group's, a revoked or deleted user, a staff role without the scope. MCP tools and bot callbacks get the same tests as HTTP.

## MCP media links and scope offers

- A media link is a bearer capability: 5 hours without sign-in, always for the enrolled, refused for someone signed in and not enrolled (who can still sign out and use it). Every open checks live state; nothing is cached. An unbound connector check must deny: keep `bind_connector_check` in `build_lms`, and test any new process that serves `POST /v1/lms/media/redeem`.
- A tool that changes state on a read, such as rotating a grant, passes `idempotent=False` to `kit.tool`. A new tool gets an entry in `tests/mcp/test_tool_catalog.py`.
- A scope offer widens a key only through `DecideScopeOffer`, by token (Telegram) or by id for the signed-in owner (web). Both share one path. The token never leaves the notification, and `ListScopeOffers` must not return it. Never offer Administration scopes: those need a step-up code.
- Second scopes inside a tool go through `guard.has_scope`: `list_files` shows flash card sets only with `flashcards:read`.

## Sharing notebooks and files

- `load_notebook` and `load_source` are closed to recipients by default; a use case opts in with `shared=True` and must then be read-only for the owner's data. Add a denial test for any new one. Recipients of a file read only through `/v1/files/shared/*`; `may_read` does not know about grants.
- Only manual notebooks and personal files are shared. Shown, copied and attached sources are limited to `VIEWABLE_KINDS`: chats stay private, and lesson, course, flash card and library sources keep their own audience.
- A viewer never gets the owner's chat settings, custom prompt, thread, labels, Studio outputs or, with hidden sources, the summary. Their chat uses their own budget and rate limit. Shared text is untrusted (`SHARED_SOURCES_RULE`), and a model-proposed Studio action is dropped.
- Attached sets are re-checked on every turn, reach the host's owner only and are not followed further. Retrieval scopes by the chosen source ids.
- Link tokens are 256-bit, stored only as SHA-256, sent in the body or URL fragment, shown once, and joining is rate limited. Unknown, disabled and revoked all answer the same 404. A revoked person stays out of the link until invited directly.
- The picker needs 3 letters, is rate limited, returns at most 10 and shows only a name.

## Rate limits and enumeration

- Sign-in, registration, codes, password reset, public shares and short links use `app/shared/rate_limit.py` with a key per IP (`client_ip.py`) and per account.
- Same status, body and timing class for "no such user" and "wrong password". Do not reveal whether a login, email or EMIS id exists.

## SSRF and fetches

- Outbound fetches of user-given URLs use the safe fetchers (`certificates/infrastructure/safe_fetcher.py`, `links/domain/url_policy.py`, the LMS link checker): http(s) only, resolve and refuse private, loopback, link-local and metadata addresses, follow redirects manually and re-check every hop, cap size and time.
- UniLibrary: never spoof `Origin` or `Referer`; a 403 opens the breaker.

## Uploads

- Check content by libmagic against a per-feature allowlist, not the extension or the client's content type. Cap size before reading the whole body. Serve user files from storage with `Content-Disposition` and never from the API origin as HTML.
- Images (faces) also pass `check_image` in `app/modules/faces/domain/image.py`: the PNG/JPEG header dimensions are capped before decoding (decompression bombs).

## Bearer tokens and devices

- Personal tokens (`ihsp_pat_`, scopes `me:read`/`me:write`) and entrance device keys are stored hashed, shown once, revocable, and record last use. Never log the secret. A new `/v1/me` write route is reachable with `me:write`; decide whether it should be.
- Vault unseal keys from `POST /v1/admin/vault/unseal` are forwarded to Vault and never logged, stored or echoed.

## Telegram widgets

- A widget (`app/interfaces/bot/widgets`, flag `IHSP_BOT__WIDGETS_ENABLED`) is HTML that runs in Telegram's sandbox. Every string of a block is model output: escape it with `esc()` as text or as a double-quoted attribute, never place it in `<script>`, `style`, an inline handler or a URL except a vetted `data-url`. The only script is the fixed click delegate; `audit()` rejects `http(s):`, `//`, `url(`, `@import`, `on*=`, script sources and form or embed tags, and a failed audit means the Markdown fallback.
- Widget code and state are public. Put no secret, token or personal data in `public_data`, `chat_data` or the HTML beyond what the answer shows. Send widgets only in private chats; a widget is non-forwardable.
- `widget_query` data is untrusted and at most 64 bytes: parse only `viz:<token>`, check the token for the sender with `visual_url`, always call `answerWidgetQuery` within 15 s, and never act on a query of an unlinked or blocked account.

## Secrets and settings

- No key in code, tests, logs, error messages or `openapi.json`. Real keys only in git-ignored files. `materials/dev.env` keeps `IHSP_OPENROUTER__API_KEY=` empty.
- A new setting with a secret gets a prod check (`IHSP_ENV=prod` refuses dev values) and an entry in `materials/.env.sample`.
- Logs and Bugsink events carry ids, not names, marks or message text.

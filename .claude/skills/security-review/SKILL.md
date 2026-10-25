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

## Rate limits and enumeration

- Sign-in, registration, codes, password reset, public shares and short links use `app/shared/rate_limit.py` with a key per IP (`client_ip.py`) and per account.
- Same status, body and timing class for "no such user" and "wrong password". Do not reveal whether a login, email or EMIS id exists.

## SSRF and fetches

- Outbound fetches of user-given URLs use the safe fetchers (`certificates/infrastructure/safe_fetcher.py`, `links/domain/url_policy.py`, the LMS link checker): http(s) only, resolve and refuse private, loopback, link-local and metadata addresses, follow redirects manually and re-check every hop, cap size and time.
- UniLibrary: never spoof `Origin` or `Referer`; a 403 opens the breaker.

## Uploads

- Check content by libmagic against a per-feature allowlist, not the extension or the client's content type. Cap size before reading the whole body. Serve user files from storage with `Content-Disposition` and never from the API origin as HTML.

## Secrets and settings

- No key in code, tests, logs, error messages or `openapi.json`. Real keys only in git-ignored files. `materials/dev.env` keeps `IHSP_OPENROUTER__API_KEY=` empty.
- A new setting with a secret gets a prod check (`IHSP_ENV=prod` refuses dev values) and an entry in `materials/.env.sample`.
- Logs and Bugsink events carry ids, not names, marks or message text.

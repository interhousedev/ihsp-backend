---
name: telegram-bot
description: Use when changing the aiogram bot in app/interfaces/bot - rendering rich text and model answers as Telegram HTML, inline buttons and callback data, approval and action tokens, streaming answers with drafts, router order, FSM states and the AI catch-all, or guest handling.
---

# Telegram bot

## Rendering

- All text goes out as Telegram HTML built by `app/interfaces/bot/richtext/` (`render.py`, `blocks.py`, `inline.py`, `chunking.py`, `latex.py`). Escape every dynamic value with `richtext.inline.escape`; never interpolate user, EMIS or model text into HTML by hand.
- Model Markdown is converted, not passed through. Unsupported tags are dropped, LaTeX becomes text, OpenUI blocks degrade to Markdown first.
- `chunking.py` splits at block boundaries under Telegram's 4096-character limit without breaking tags.
- Copy comes from `locales/{uz,ru,en}` (see `copy-and-i18n`).

## Buttons and callbacks

- Callback data is at most **64 bytes UTF-8** (`richtext/buttons.py`, `callback_data_fits`). Never put ids that can grow, text or JSON in it.
- For anything that acts (approve a tool call, undo, share), put a short **server-side single-use token** in the callback and keep the payload in Redis bound to the user: `store.take_call(token, user_id)` consumes it. Test replay, another user and expiry.
- Typed callbacks shared with notifications live in `app/shared/contracts/callbacks.py` (for example `ExcuseCb` for curator approve/reject, handled in `routers/common/excuses`); the decision goes through the excuse use case, which checks the actor.

## Commands

- `utilities/commands.py` holds `COMMAND_KEYS`; `bot.set_commands` publishes the full list per language, and `/start` or `/menu` narrows the chat's list to the user's roles (`set_role_commands`, reset on Log out). A new role-only command goes into `STUDENT_ONLY` or `TEACHER_ONLY`, with a `bot-command-*` key in all three locales.
- `/help` lists the user's commands from the same catalogue; never hand-write the list in a locale string.

## Hub, navigation, pagination, errors

- `/menu`, `/start` and `m:menu` open one hub (`keyboards/main_menu.py`): Study (Work for teachers), Tools and Account sections with `none_button` headers, then the mini app button. Screens reached from the hub are edited in place (`reply_edit.show` falls back to a send).
- Every sub-screen ends with `utilities/navigation.nav_rows(i18n, parent)`: `← Back` to the parent (the hub by default) and `⌂ Menu`. `keyboards/back_to_menu.get` is that footer for first-level screens.
- Lists longer than 8 items use `utilities/pagination` (`paginate`, `pager_row`) and the one `PageCb(kind, page)`; register a handler per `kind` (`hw` for homework).
- Layout: bold title, blank line, body, `<i>` footer. Errors go through `utilities/errors` (`error_html`, `error_text`). Empty states say what is missing and keep an action button.
- Screens with a richer web page add an Open in app button via `BotUrls.page(roles, path)`.

## Streaming

- `assistant/stream.py`: private chats use `sendMessageDraft` (Bot API 9) for the live answer; the draft is ephemeral, so the finished answer is always sent as a normal message. If drafts fail, fall back to one message edited at most once a second.

## Routers and FSM

- Order matters (`routers/__init__.py`): `cancel`, `chat_member`, `security`, `guest` (before login and any catch-all), `login`, feature routers, and the AI assistant catch-all **last**.
- A user in an FSM state (entering a mark, a homework text, a work-off) must reach that state's handler, never the AI catch-all. Filter the catch-all on "no state" and test both orders.
- Guests (not linked) see only the guest router and public knowledge.

## Tests

`tests/bot` with a fake bot: assert the exact HTML, the callback sizes and the router a message lands in.

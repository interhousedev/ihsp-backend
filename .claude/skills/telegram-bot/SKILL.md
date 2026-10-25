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

## Streaming

- `assistant/stream.py`: private chats use `sendMessageDraft` (Bot API 9) for the live answer; the draft is ephemeral, so the finished answer is always sent as a normal message. If drafts fail, fall back to one message edited at most once a second.

## Routers and FSM

- Order matters (`routers/__init__.py`): `cancel`, `chat_member`, `security`, `guest` (before login and any catch-all), `login`, feature routers, and the AI assistant catch-all **last**.
- A user in an FSM state (entering a mark, a homework text, a work-off) must reach that state's handler, never the AI catch-all. Filter the catch-all on "no state" and test both orders.
- Guests (not linked) see only the guest router and public knowledge.

## Tests

`tests/bot` with a fake bot: assert the exact HTML, the callback sizes and the router a message lands in.

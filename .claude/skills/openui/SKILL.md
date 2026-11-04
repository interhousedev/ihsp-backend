---
name: openui
description: Use when changing generative UI blocks in AI answers (app/shared/openui) - the component catalogue shared with iht-web, the prompt lines that teach the model the catalogue, validation, the one-shot repair task, dropping unsafe blocks, and degrading to Markdown for the bot and plain clients.
---

# OpenUI

Code: `app/shared/openui/` (`catalog.json`, `catalog.py`, `blocks.py`, `validate.py`, `finalize.py`, `degrade.py`, `prompt.py`, `visual.py`).

## Catalogue

- `catalog.json` is the single list of components and props, shared with `iht-web` (`packages/features-core/src/openui`). A new component or prop changes both repositories in step; the web renders only what it knows.
- Subsets (`chat`, ...) limit what each surface may use. The prompt lines come from `finalize.catalog_lines(subset)` (`compact=True` in the chat prompt leaves out list sizes; validation still enforces them); never hand-write component docs in a system prompt.

## Chat safeguards

The model's compliance is not relied on; `ContinueTurn` does this on the server. Narration and language cover student, Administration and author chats (the guest assistant uses the same two helpers); table conversion and the last-step rule are the same for them. Notebook chat takes only the volatile language line and the Uzbek letters; Studio stays out of it.

- `app/shared/ai/narration.py` removes leading notes about the user, the request or the tools, in the final text and over the stream (`NarrationFilter`). A pattern must name that kind of note: "the student" as a topic stays, and the student patterns are off in Administration chats and when the user's message mentions a student. Add a false-positive test with every pattern.
- `tables.markdown_tables_to_blocks` (finalizer option `convert_tables`) turns a Markdown table into a Table block during finalize; links, citations, formulas, odd rows and code stay Markdown. The stream shows the Markdown table until `done` replaces it.
- `app/shared/ai/answer_language.py` picks the answer language from the user's message, falling back to the locale. It goes in the last prompt line, after the cache breakpoint (`with_volatile_tail`), so the stable prefix stays cached.
- `app/shared/ai/uzbek.py` corrects Uzbek apostrophes to ʼ in the final answer (chat, notebook; `UzbekStream` for the guest), leaving code, addresses and formulas alone.
- The last step of a turn, or the step after a round of only repeated calls, sends `tool_choice: none` (`LlmTuning.answer_only`) and ignores any tool call the model still returns.

## Finalize (before an answer is stored)

1. Split the answer into text and fenced blocks (`blocks.split_blocks`).
2. `validate_block(source, subset)`: known component, known props, types, sizes, safe URLs (https only, no `javascript:`/`data:`), no raw HTML.
3. A broken block goes **once**, with its errors, to the `OPENUI_REPAIR` task, then is validated again.
4. Still broken or unsafe: drop the block, keep the text around it. Never store an invalid block.

The repair is an ordinary model call through the recording gateway: it is counted in the ledger and refused for users whose AI access is revoked.

## Degrade

- `degrade.degrade_to_markdown` / `block_markdown` render every component as Markdown (tables, lists, titles) for the Telegram bot, mail and clients without OpenUI. A new component needs its degrade rule and a test.

## Tests

For each component: a valid block, each invalid prop, an unsafe URL, the repair path with a fake model (fixed, still broken), and the Markdown rendering.

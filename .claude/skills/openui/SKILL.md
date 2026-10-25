---
name: openui
description: Use when changing generative UI blocks in AI answers (app/shared/openui) - the component catalogue shared with iht-web, the prompt lines that teach the model the catalogue, validation, the one-shot repair task, dropping unsafe blocks, and degrading to Markdown for the bot and plain clients.
---

# OpenUI

Code: `app/shared/openui/` (`catalog.json`, `catalog.py`, `blocks.py`, `validate.py`, `finalize.py`, `degrade.py`, `prompt.py`, `visual.py`).

## Catalogue

- `catalog.json` is the single list of components and props, shared with `iht-web` (`packages/features-core/src/openui`). A new component or prop changes both repositories in step; the web renders only what it knows.
- Subsets (`chat`, ...) limit what each surface may use. The prompt lines come from `finalize.catalog_lines(subset)`; never hand-write component docs in a system prompt.

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

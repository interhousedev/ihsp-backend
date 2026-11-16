---
name: prompts
description: Use for editable AI prompts: PromptRegistry slots, overrides, versions, tracing, analytics; not for Studio quality rules.
---

# Prompts (PromptRegistry)

Code: `app/modules/ai/domain/prompt_registry.py` (slots, `apply_overrides`, `resolve`), `app/modules/ai/application/prompt_registry.py` (`PromptRegistry`, `PromptAdmin`, `PromptAnalytics`), ports in `app/modules/ai/ports/prompts.py`.

## Contract

- A **slot** is one named piece (`task`, `name`) of a task's instructions with a built-in text (may hold `{placeholders}`). Every model call site must go through the registry: builders that know their locale call `PromptRegistry.resolve`; other builders keep producing the built-in text and the recording gateway calls `rewrite`, which swaps the active version into the slot. The text reaching the model is the active version, else the **built-in fallback**; the built-in must always work with an empty database.
- A new call site: define its `AiTask` in `app/shared/ai_tasks.py`, declare its slots with built-in text next to the builder, keep the placeholders the builder fills. Never hard-code a prompt that bypasses the registry; never edit a stored version in place.
- Admin overrides are **versioned**: `put_version` stores a new version (per locale or all locales ""), one version per slot and locale is active, `activate` and `revert` switch it; each change is audited (`admin.prompt_*`) in the same transaction and the saved text is validated (`check_override`: placeholders and locale). The cache lives 30 s (`OVERRIDE_TTL_SECONDS`); the writing process invalidates it at once.
- **Tracing metadata**: each call carries a `PromptRef` (slot, version, hash) into the usage ledger and the Langfuse trace; `private_content` tasks still send no text, only the reference.
- **Analytics**: `PromptAnalytics.report` joins call stats (cost, tokens, success) and ratings per version so administrators compare versions; keep new tasks' feedback flowing into it.

## Checks

Tests: the domain unit tests for `apply_overrides`, the application tests with the fake repositories, and one test per new slot that the built-in text equals the old prompt. A new table or column: `scripts/check_migrations.sh`. Routes: export OpenAPI. Prompt copy follows the `copy-and-i18n` skill.

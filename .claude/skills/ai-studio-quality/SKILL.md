---
name: ai-studio-quality
description: Use when changing notebook Studio generation (quizzes, flash cards, slides, other artifacts), AI task prompts or structured-output schemas in app/modules/notebooks - the plan-then-generate pipeline, item self-containment and stimulus rules, blueprint quotas, verify and refill, budget estimates, the real-model eval harness, and the 16 nullable/union parameter limit with NOT_NULL.
---

# AI Studio quality

The pipeline is `app/modules/notebooks/application/assessment_pipeline.py`; the domain is `app/modules/notebooks/domain/assessment/`.

## Pipeline

1. **Profile** sources with a cheap task (`STUDIO_SOURCE_PROFILE`); rules guess when it fails.
2. **Mode**: requested, else from the focus text, else from the profiles.
3. **Blueprint**: a cheap planner (`STUDIO_ASSESSMENT_PLAN`) proposes slots; **code** enforces the exact count and the template quota. Never trust the model's count.
4. **Batches**: the kind's task (`STUDIO_QUIZ`, `STUDIO_FLASHCARDS`) writes one blueprint slice at a time (`BATCH_MAX_ITEMS`).
5. **Check**: code rules first (unseen passages, stimulus, duplicates, kind validation), then a cheap solver without sources (`STUDIO_ITEM_VERIFY`). Rejected slots are written again up to `assessment_fill_rounds` times.

Profile, plan and check are best effort: a failure falls back to rules, never fails the artifact.

## Item rules

- **Self-contained**: an item never says "according to the text", "in the passage above", "source 2". A student sees one item alone.
- **Stimulus**: if an item needs a passage, table or code, the item carries it. No item refers to a stimulus it does not include.
- One correct answer; distractors plausible and of similar length; no "all of the above".
- Language follows the notebook; terms ПК/ИК; Uzbek uses `ʼ`.

## Budget

- `domain/assessment/cost.py` (`pipeline_estimate`) estimates the whole run before it starts; it is a soft pre-check against the user's limits. Update it when you add a stage or a retry.
- Every stage is a named AI task in `app/shared/ai_tasks.py` so the ledger and access guard see it.

## Structured output

- Build schemas with `to_strict_schema()` (`domain/artifacts/strict.py`): every property required, `additionalProperties: false`.
- **At most 16 union or nullable parameters** per schema, or Anthropic answers HTTP 400. Mark fields that may be missing in pydantic but must not be null for the model with `json_schema_extra=NOT_NULL`.
- No recursive schemas. Add a unit test that counts the nullable/union parameters of every new schema.

## Evaluating

- Unit tests run against fake LLMs with scripted answers: cover refill, a broken plan, a failing verifier, the quota.
- Quality changes are checked with the eval harnesses (`scripts/nb_eval_slides.py`, `scripts/nb_eval_html.py`, `scripts/vector_eval.py`) against a real model, **only when the user asks**, with keys from git-ignored files. Outputs go to `eval/out/` (ignored). Compare before/after on the same sources and report pass rates, not impressions.

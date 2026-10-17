"""Student render of a step: the content without any correctness data (LMS-17)."""

from typing import Any

from app.modules.lms.domain.step_content import (
    FlashcardsBlock,
    H5PBlock,
    InteractiveVideoBlock,
    Question,
    StepContent,
    TestBlock,
    TextBlock,
    VideoBlock,
)


def render_step(content: StepContent, *, revision_id: str) -> dict[str, Any]:
    """Return ``{"revision_id", "title", "blocks"}`` for ``StepView``.

    The result depends only on the revision, so it can be cached by revision id.
    Per-student fields are placeholders for the caller to fill: ``best`` and
    ``open_attempt_id`` of test blocks, ``attempts_left`` (the full limit here)
    and ``due`` of flash card blocks. Correct answers, answer configs and
    explanations are never included.
    """
    blocks = [_render_block(block) for block in content.blocks]
    return {"revision_id": revision_id, "title": content.title, "blocks": blocks}


def _render_block(
    block: (
        TextBlock
        | VideoBlock
        | TestBlock
        | FlashcardsBlock
        | H5PBlock
        | InteractiveVideoBlock
    ),
) -> dict[str, Any]:
    """Render one block without correctness data."""
    if isinstance(block, H5PBlock):
        return {
            "id": block.id,
            "type": "h5p",
            "package_id": block.package_id,
            "title": block.title,
            "main_library": block.main_library,
            "passing_score_pct": block.passing_score_pct,
        }
    if isinstance(block, InteractiveVideoBlock):
        return {
            "id": block.id,
            "type": "interactive_video",
            "source": block.source,
            "url": block.url,
            "file_id": block.file_id,
            "caption": block.caption,
            "interactions": [
                {
                    "id": item.id,
                    "at_sec": item.at_sec,
                    "kind": item.kind,
                    "text": item.text,
                    "url": item.url,
                    "multiple": item.multiple,
                    "points": item.points,
                    "options": [{"id": o.id, "text": o.text} for o in item.options],
                }
                for item in sorted(block.interactions, key=lambda i: i.at_sec)
            ],
        }
    if isinstance(block, TextBlock):
        return {"id": block.id, "type": "text", "markdown": block.markdown}
    if isinstance(block, VideoBlock):
        return {
            "id": block.id,
            "type": "video",
            "source": block.source,
            "url": block.url,
            "file_id": block.file_id,
            "caption": block.caption,
        }
    if isinstance(block, TestBlock):
        config = block.config
        total = len(block.questions)
        count = min(config.pool_size, total) if config.pool_size else total
        return {
            "id": block.id,
            "type": "test",
            "rules": {
                "questions": count,
                "attempts_left": config.max_attempts,
                "time_limit_sec": config.time_limit_sec,
                "passing_score_pct": config.passing_score_pct,
            },
            "best": None,
            "open_attempt_id": None,
        }
    return {
        "id": block.id,
        "type": "flashcards",
        "cards_count": len(block.cards),
        "due": 0,
    }


def render_questions(
    test: TestBlock,
    question_ids: list[str],
    option_order: dict[str, list[str]],
    params: dict[str, dict[str, float]] | None = None,
) -> list[dict[str, Any]]:
    """Return the ``AttemptView.questions`` of one attempt variant.

    Questions follow ``question_ids``; options follow ``option_order`` (options
    missing from it keep their original order at the end). No correctness data.

    Raises:
        ValueError: ``question_ids`` names a question that is not in the test.
    """
    by_id = {question.id: question for question in test.questions}
    rendered: list[dict[str, Any]] = []
    for question_id in question_ids:
        if question_id not in by_id:
            raise ValueError(f"unknown question id: {question_id}")
        rendered.append(
            _render_question(
                by_id[question_id], option_order, (params or {}).get(question_id, {})
            )
        )
    return rendered


def fill_prompt(prompt: str, params: dict[str, float]) -> str:
    """Replace ``{name}`` by the attempt's value of the variable."""
    for name, value in params.items():
        prompt = prompt.replace("{" + name + "}", f"{value:g}")
    return prompt


def _render_question(
    question: Question, option_order: dict[str, list[str]], params: dict[str, float]
) -> dict[str, Any]:
    """Render one question for an attempt."""
    item: dict[str, Any] = {
        "id": question.id,
        "type": question.type,
        "prompt": fill_prompt(question.prompt, params),
        "points": question.points,
    }
    if question.pairs is not None:
        by_pair = {pair.id: pair for pair in question.pairs}
        order = [pid for pid in option_order.get(question.id, []) if pid in by_pair]
        order += [pid for pid in by_pair if pid not in order]
        item["lefts"] = [{"id": p.id, "text": p.left} for p in question.pairs]
        item["rights"] = [{"id": pid, "text": by_pair[pid].right} for pid in order]
    if question.table is not None:
        item["table"] = {
            "rows": question.table.rows,
            "columns": question.table.columns,
        }
    if question.blanks is not None:
        item["blanks"] = len(question.blanks)
    if question.formula is not None:
        item["variables"] = question.formula.variables
    if question.code is not None:
        item["code"] = {
            "language": question.code.language,
            "starter": question.code.starter,
            "auto": bool(question.code.expected_outputs),
        }
    if question.options is not None:
        by_id = {option.id: option for option in question.options}
        order = [oid for oid in option_order.get(question.id, []) if oid in by_id]
        order += [oid for oid in by_id if oid not in order]
        item["options"] = [{"id": oid, "text": by_id[oid].text} for oid in order]
    return item

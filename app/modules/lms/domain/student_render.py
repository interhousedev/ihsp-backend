"""Student render of a step: the content without any correctness data (LMS-17)."""

from typing import Any

from app.modules.lms.domain.step_content import (
    FlashcardsBlock,
    Question,
    StepContent,
    TestBlock,
    TextBlock,
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


def _render_block(block: TextBlock | TestBlock | FlashcardsBlock) -> dict[str, Any]:
    """Render one block without correctness data."""
    if isinstance(block, TextBlock):
        return {"id": block.id, "type": "text", "markdown": block.markdown}
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
        rendered.append(_render_question(by_id[question_id], option_order))
    return rendered


def _render_question(
    question: Question, option_order: dict[str, list[str]]
) -> dict[str, Any]:
    """Render one question for an attempt."""
    item: dict[str, Any] = {
        "id": question.id,
        "type": question.type,
        "prompt": question.prompt,
        "points": question.points,
    }
    if question.options is not None:
        by_id = {option.id: option for option in question.options}
        order = [oid for oid in option_order.get(question.id, []) if oid in by_id]
        order += [oid for oid in by_id if oid not in order]
        item["options"] = [{"id": oid, "text": by_id[oid].text} for oid in order]
    return item

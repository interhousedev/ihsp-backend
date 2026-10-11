"""Student render: no correctness data ever leaves the server (LMS-17)."""

import json
from typing import Any

from app.modules.lms.domain.step_content import StepContent, TestBlock
from app.modules.lms.domain.student_render import render_questions, render_step
from tests.models.test_step_content import EXAMPLE

import pytest

FORBIDDEN_KEYS = {"correct", "answer", "explanation"}


def _keys(value: Any) -> set[str]:
    """Collect every dict key anywhere in a nested structure."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list | tuple):
        return {k for item in value for k in _keys(item)}
    return set()


@pytest.fixture
def content() -> StepContent:
    """The spec example step."""
    return StepContent.model_validate(EXAMPLE)


@pytest.fixture
def block_under_test(content: StepContent) -> TestBlock:
    """The test block of the example."""
    block = content.blocks[1]
    assert isinstance(block, TestBlock)
    return block


def test_rendered_step_has_no_correctness_data(content: StepContent) -> None:
    rendered = render_step(content, revision_id="rev-1")

    assert not _keys(rendered) & FORBIDDEN_KEYS
    assert "Power rule." not in json.dumps(rendered, ensure_ascii=False)


def test_rendered_step_carries_revision_and_title(content: StepContent) -> None:
    rendered = render_step(content, revision_id="rev-1")

    assert rendered["revision_id"] == "rev-1"
    assert rendered["title"] == "Derivative rules"


def test_text_block_is_rendered_as_is(content: StepContent) -> None:
    block = render_step(content, revision_id="r")["blocks"][0]

    assert block == {
        "id": "b7f3Kq2x",
        "type": "text",
        "markdown": "The derivative of ...",
    }


RICH_MARKDOWN = (
    "**Bold** *italic* <u>under</u> ~~strike~~ `code` ||spoiler||\n\n"
    "Inline $\\frac{a}{b}$ and $$x^2$$, prices $5 and \\$10.\n\n"
    "$$\n\\int_0^1 x^2 \\, dx \\\\ a & b\n$$\n\n"
    "> quote\n\n"
    "```python\nprint('<b>&amp;</b>')\n```\n\n"
    "<script>alert(1)</script>"
)


def test_text_block_with_math_and_formatting_is_rendered_unchanged() -> None:
    """LMS-17: LaTeX, spoilers, `<u>` and raw HTML reach the student as written.

    The web renderer is the only place that interprets (and escapes) Markdown.
    """
    content = StepContent.model_validate(
        {
            "title": "Rich",
            "blocks": [{"id": "b1", "type": "text", "markdown": RICH_MARKDOWN}],
        }
    )

    block = render_step(content, revision_id="r")["blocks"][0]

    assert block["markdown"] == RICH_MARKDOWN


def test_block_under_test_shows_rules_but_no_questions(content: StepContent) -> None:
    block = render_step(content, revision_id="r")["blocks"][1]

    assert block["type"] == "test"
    assert block["rules"] == {
        "questions": 2,
        "attempts_left": 3,
        "time_limit_sec": 600,
        "passing_score_pct": 60,
    }
    assert block["best"] is None
    assert block["open_attempt_id"] is None
    assert "questions" not in block


def test_question_count_is_limited_by_the_pool_size(content: StepContent) -> None:
    test = content.blocks[1]
    assert isinstance(test, TestBlock)
    test.config.pool_size = 1

    block = render_step(content, revision_id="r")["blocks"][1]

    assert block["rules"]["questions"] == 1


def test_flashcards_block_shows_only_the_card_count(content: StepContent) -> None:
    block = render_step(content, revision_id="r")["blocks"][2]

    assert block == {"id": "bc4dZ6vN", "type": "flashcards", "cards_count": 1, "due": 0}


def test_attempt_questions_have_no_correctness_data(
    block_under_test: TestBlock,
) -> None:
    questions = render_questions(block_under_test, ["q4Nz8Wp1", "q8Fj3Rs5"], {})

    assert not _keys(questions) & FORBIDDEN_KEYS


def test_attempt_questions_follow_the_variant_order(
    block_under_test: TestBlock,
) -> None:
    questions = render_questions(
        block_under_test,
        ["q8Fj3Rs5", "q4Nz8Wp1"],
        {"q4Nz8Wp1": ["o3Hb7Yd2", "o9Tr2Ck6"]},
    )

    assert [question["id"] for question in questions] == ["q8Fj3Rs5", "q4Nz8Wp1"]
    assert [option["id"] for option in questions[1]["options"]] == [
        "o3Hb7Yd2",
        "o9Tr2Ck6",
    ]
    assert questions[1]["options"][0] == {"id": "o3Hb7Yd2", "text": "x"}


def test_questions_without_options_have_no_options_key(
    block_under_test: TestBlock,
) -> None:
    questions = render_questions(block_under_test, ["q8Fj3Rs5"], {})

    assert questions == [
        {
            "id": "q8Fj3Rs5",
            "type": "number",
            "prompt": "f(x)=3x, f′(5)=?",
            "points": 1.0,
        }
    ]


def test_options_missing_from_the_order_keep_their_place_at_the_end(
    block_under_test: TestBlock,
) -> None:
    questions = render_questions(
        block_under_test, ["q4Nz8Wp1"], {"q4Nz8Wp1": ["o3Hb7Yd2"]}
    )

    assert [option["id"] for option in questions[0]["options"]] == [
        "o3Hb7Yd2",
        "o9Tr2Ck6",
    ]


def test_unknown_question_id_is_an_error(block_under_test: TestBlock) -> None:
    with pytest.raises(ValueError, match="unknown question"):
        render_questions(block_under_test, ["nope"], {})

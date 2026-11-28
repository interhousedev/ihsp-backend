"""LMS-15, LMS-23: blocks built by MCP tools match the API contract shape."""

from app.interfaces.mcp.cards import FlashcardInput
from app.interfaces.mcp.errors import McpInvalidInputError
from app.interfaces.mcp.lms.blocks import (
    build_flashcards_block,
    build_question,
    build_test_block,
    build_text_block,
)
from app.interfaces.mcp.lms.inputs import OptionInput, QuestionInput, QuizSettingsInput

import pytest


def test_text_block_has_an_empty_id_for_the_server_to_fill() -> None:
    """LMS-23: ids are assigned by the server, never by the AI client."""
    assert build_text_block("hi") == {"id": "", "type": "text", "markdown": "hi"}


def test_flashcards_block_cards_have_empty_ids() -> None:
    """LMS-18, LMS-23: cards of a block."""
    block = build_flashcards_block([FlashcardInput(front="f", back="b")])

    assert block == {
        "id": "",
        "type": "flashcards",
        "cards": [{"id": "", "front": "f", "back": "b"}],
    }


def test_test_block_defaults_match_the_editor_defaults() -> None:
    """LMS-16: unset settings get documented defaults."""
    block = build_test_block(None, [])

    assert block["config"] == {
        "max_attempts": None,
        "passing_score_pct": 60,
        "shuffle_questions": False,
        "shuffle_options": False,
        "pool_size": None,
        "time_limit_sec": None,
        "cooldown_sec": None,
        "show_answers": "after_submit",
    }
    assert block["questions"] == []


def test_test_block_keeps_given_settings() -> None:
    """LMS-16: settings pass through."""
    block = build_test_block(QuizSettingsInput(pool_size=5, show_answers="never"), [])

    assert block["config"]["pool_size"] == 5
    assert block["config"]["show_answers"] == "never"


def test_single_choice_question_shape() -> None:
    """LMS-15: options carry correct and pinned flags."""
    question = QuestionInput(
        type="single",
        prompt="q",
        explanation="because",
        options=[OptionInput(text="a", correct=True), OptionInput(text="b")],
    )

    built = build_question(question)

    assert built["type"] == "single"
    assert built["explanation"] == "because"
    assert built["points"] == 1
    assert [o["correct"] for o in built["options"]] == [True, False]
    assert "answer" not in built


@pytest.mark.parametrize(
    "question",
    [
        QuestionInput(
            type="single", prompt="q", options=[OptionInput(text="a", correct=True)]
        ),
        QuestionInput(
            type="single",
            prompt="q",
            options=[OptionInput(text="a"), OptionInput(text="b")],
        ),
        QuestionInput(
            type="multiple",
            prompt="q",
            options=[OptionInput(text="a"), OptionInput(text="b")],
        ),
        QuestionInput(type="text", prompt="q"),
        QuestionInput(type="number", prompt="q"),
    ],
)
def test_invalid_questions_raise_an_input_error(question: QuestionInput) -> None:
    """Each question type needs its own data."""
    with pytest.raises(McpInvalidInputError):
        build_question(question)


def test_text_question_accepts_a_regex_alone() -> None:
    """LMS-15: text answers may be a regex."""
    built = build_question(QuestionInput(type="text", prompt="q", regex="^a+$"))

    assert built["answer"] == {"accepted": [], "regex": "^a+$", "case_sensitive": False}


def test_list_block_types_covers_every_domain_block_type() -> None:
    """A domain block type without an author input model fails here."""
    from typing import get_args

    from app.interfaces.mcp.lms.tools.list_block_types import describe_block_type
    from app.modules.lms.domain.step_content import Block
    from app.shared.contracts.lms_blocks import AUTHOR_BLOCK_MODELS

    domain = {m.model_fields["type"].default for m in get_args(get_args(Block)[0])}
    described = {describe_block_type(m)["type"] for m in AUTHOR_BLOCK_MODELS}
    assert domain <= described
    for model in AUTHOR_BLOCK_MODELS:
        info = describe_block_type(model)
        assert info["example"]["type"] == info["type"]
        assert info["description"]

"""LMS-AI-STUDIO: converting Studio outputs into LMS blocks and outlines."""

from typing import Any

from app.modules.notebooks.application.course_convert import (
    clean_plan,
    deck_to_blocks,
    draft_of,
    draft_to_content,
    plan_of,
    plan_to_sections,
    quiz_to_blocks,
    quiz_to_questions,
)
from app.shared.contracts.lms_blocks import (
    BlockInputError,
    CoursePlanInput,
    FlashcardsBlockInput,
    PlanSectionInput,
    PlanStepInput,
    StepDraftInput,
    TestBlockInput,
    TextBlockInput,
)

import pytest

QUIZ: dict[str, Any] = {
    "title": "Quiz",
    "questions": [
        {
            "id": "q1",
            "type": "single",
            "prompt": "Which gas is released?",
            "options": [
                {"id": "a", "text": "Nitrogen"},
                {"id": "b", "text": "Oxygen [S1:P1]"},
                {"id": "c", "text": "Hydrogen"},
            ],
            "correct": ["b"],
            "explanation": "Water is split [[S1:P2]].",
            "hint": "Think of water",
            "difficulty": "easy",
            "topic": "Light",
            "refs": ["S1:P1"],
        },
        {
            "id": "q2",
            "type": "multiple",
            "prompt": "Which are products?",
            "options": [
                {"id": "a", "text": "Glucose"},
                {"id": "b", "text": "Oxygen"},
                {"id": "c", "text": "Carbon dioxide"},
                {"id": "d", "text": "Nitrogen"},
            ],
            "correct": ["a", "b"],
            "explanation": "Both are made.",
            "hint": None,
            "refs": [],
        },
        {
            "id": "q3",
            "type": "true_false",
            "prompt": "Plants are green because of chlorophyll.",
            "options": [
                {"id": "true", "text": "True"},
                {"id": "false", "text": "False"},
            ],
            "correct": ["true"],
            "explanation": "Chlorophyll reflects green.",
            "refs": [],
        },
    ],
}
DECK: dict[str, Any] = {
    "title": "Cards",
    "cards": [
        {
            "id": "c1",
            "front": "Where is light absorbed?",
            "back": "In the thylakoids [S1:P1].",
            "hint": "membranes",
            "topic": "Light",
            "refs": ["S1:P1"],
        },
        {"id": "c2", "front": "Product?", "back": "Glucose", "refs": []},
    ],
}


# - - - Quiz - - -


def test_a_quiz_becomes_a_test_block_with_the_right_options() -> None:
    """LMS-AI-STUDIO: single and multiple map one to one; explanations stay."""
    converted = quiz_to_blocks(QUIZ)

    (block,) = converted.blocks
    assert block["type"] == "test" and block["id"] == ""
    first, second, third = block["questions"]
    assert (first["type"], second["type"], third["type"]) == (
        "single",
        "multiple",
        "single",
    )
    assert [o["text"] for o in first["options"] if o["correct"]] == ["Oxygen"]
    assert [o["text"] for o in second["options"] if o["correct"]] == [
        "Glucose",
        "Oxygen",
    ]
    assert first["explanation"] == "Water is split."
    assert block["config"]["passing_score_pct"] == 60


def test_true_false_and_hints_are_reduced_and_reported() -> None:
    """LMS-AI-STUDIO: what the LMS cannot express is reduced, with a note."""
    converted = quiz_to_blocks(QUIZ)

    third = converted.blocks[0]["questions"][2]
    assert [(o["text"], o["correct"]) for o in third["options"]] == [
        ("True", True),
        ("False", False),
    ]
    assert converted.notes == [
        "1 true/false question(s) became single choice questions with two options.",
        "The hints of 1 question(s) were not copied.",
    ]


def test_quiz_questions_are_lms_questions() -> None:
    """LMS-AI-STUDIO: the assistant can reuse the questions with other settings."""
    questions, _ = quiz_to_questions(QUIZ)

    assert [q.type for q in questions] == ["single", "multiple", "single"]
    assert questions[0].options is not None and len(questions[0].options) == 3


def test_an_empty_quiz_is_refused() -> None:
    """LMS-AI-STUDIO: nothing to apply."""
    with pytest.raises(BlockInputError, match="no questions"):
        quiz_to_blocks({"questions": []})


def test_a_quiz_question_with_two_right_answers_for_single_is_refused() -> None:
    """LMS-AI-STUDIO: the LMS rules are checked before anything is written."""
    broken = {"questions": [{**QUIZ["questions"][0], "correct": ["a", "b"]}]}

    with pytest.raises(BlockInputError, match="exactly one correct"):
        quiz_to_blocks(broken)


# - - - Flash cards - - -


def test_a_deck_becomes_a_flashcards_block() -> None:
    """LMS-AI-STUDIO: front and back, no labels; hints and topics are reported."""
    converted = deck_to_blocks(DECK)

    (block,) = converted.blocks
    assert block["type"] == "flashcards"
    assert block["cards"][0] == {
        "id": "",
        "front": "Where is light absorbed?",
        "back": "In the thylakoids.",
    }
    assert converted.notes == ["The hints and topics of the cards were not copied."]


def test_a_deck_without_usable_cards_is_refused() -> None:
    """LMS-AI-STUDIO: empty sides are skipped; an empty deck cannot be applied."""
    with pytest.raises(BlockInputError, match="no usable cards"):
        deck_to_blocks({"cards": [{"front": "Q", "back": " "}]})


# - - - Lesson draft - - -


def lesson(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": "Light [S1:P1]",
        "blocks": [
            {"type": "text", "markdown": "## Intro [[S1:P1]]\n\nPlants <i>live</i>."},
            {
                "type": "flashcards",
                "cards": [{"front": "Q (S1:P1)", "back": "A"}],
            },
            {
                "type": "test",
                "questions": [
                    {
                        "type": "single",
                        "prompt": "Pick one",
                        "options": [
                            {"text": "A", "correct": True},
                            {"text": "B", "correct": False},
                        ],
                    }
                ],
            },
        ],
    }
    return {**base, **changes}


def test_a_lesson_becomes_step_content_without_labels() -> None:
    """LMS-AI-STUDIO: markdown cleaned, ids empty, blocks in order."""
    content = draft_to_content(draft_of(lesson()))

    assert content["title"] == "Light"
    assert [b["type"] for b in content["blocks"]] == ["text", "flashcards", "test"]
    assert content["blocks"][0]["markdown"] == "### Intro\n\nPlants live."
    assert content["blocks"][1]["cards"][0]["front"] == "Q"
    assert content["blocks"][2]["questions"][0]["options"][0]["correct"] is True
    assert all(block["id"] == "" for block in content["blocks"])


def test_an_edited_lesson_is_cleaned_again() -> None:
    """LMS-AI-STUDIO: whatever the author typed is cleaned like the model's text."""
    draft = StepDraftInput(
        title="T", blocks=[TextBlockInput(markdown="# Heading S1:P3\n\ntext")]
    )

    content = draft_to_content(draft)

    assert content["blocks"][0]["markdown"] == "### Heading\n\ntext"


def test_a_text_block_that_is_only_a_label_is_refused() -> None:
    """LMS-AI-STUDIO: an empty block would be rejected by the LMS later."""
    draft = StepDraftInput(title="T", blocks=[TextBlockInput(markdown="[S1:P1]")])

    with pytest.raises(BlockInputError, match="no text"):
        draft_to_content(draft)


def test_a_lesson_that_does_not_match_the_contract_is_refused() -> None:
    """LMS-AI-STUDIO: the error names the field."""
    with pytest.raises(BlockInputError, match="blocks"):
        draft_of({"title": "T", "blocks": []})


def test_a_test_block_with_a_bad_question_is_refused_on_conversion() -> None:
    """LMS-AI-STUDIO: `build_step_content` checks the question rules."""
    bad = lesson()
    bad["blocks"][2]["questions"][0]["options"][1]["correct"] = True

    with pytest.raises(BlockInputError, match="exactly one correct"):
        draft_to_content(draft_of(bad))


def test_blocks_other_than_text_pass_through_unchanged_types() -> None:
    """LMS-AI-STUDIO: the contract classes are what the conversion works on."""
    draft = draft_of(lesson())

    assert isinstance(draft.blocks[1], FlashcardsBlockInput)
    assert isinstance(draft.blocks[2], TestBlockInput)


# - - - Course plan - - -


PLAN: dict[str, Any] = {
    "title": "Course",
    "language": "ru",
    "summary": "Overview [S1:P1]",
    "goals": ["Explain photosynthesis"],
    "sections": [
        {
            "title": "Light",
            "goals": ["Describe light"],
            "refs": ["S1:P1"],
            "steps": [
                {
                    "title": "Photons",
                    "goals": ["Explain photons"],
                    "summary": "Photons carry energy [S1:P2].",
                    "refs": ["S1:P2"],
                },
                {"title": "Pigments", "goals": [], "summary": ""},
            ],
        }
    ],
}


def test_a_plan_becomes_the_outline_with_briefs_in_its_language() -> None:
    """LMS-AI-STUDIO: `outline_sections` with the plan's own language."""
    sections = plan_to_sections(plan_of(PLAN), "ru")

    assert [s["title"] for s in sections] == ["Light"]
    first, second = sections[0]["steps"]
    assert first["title"] == "Photons"
    assert first["brief"] == (
        "**Цели обучения**\n\n- Explain photons\n\n**План**\n\nPhotons carry energy."
    )
    assert second["brief"] == ""


def test_an_unknown_language_falls_back_to_english_labels() -> None:
    """LMS-AI-STUDIO: the briefs always have labels."""
    sections = plan_to_sections(plan_of(PLAN), "")

    assert sections[0]["steps"][0]["brief"].startswith("**Learning goals**")


def test_an_edited_plan_loses_labels_but_keeps_the_authors_titles() -> None:
    """LMS-AI-STUDIO: no renaming of the author's titles."""
    plan = CoursePlanInput(
        summary="S [S1:P1]",
        sections=[
            PlanSectionInput(
                title="1. My section",
                steps=[PlanStepInput(title="Step [S1:P2]", goals=["g (S1:P1)"])],
            )
        ],
    )

    cleaned = clean_plan(plan)

    assert cleaned.summary == "S"
    assert cleaned.sections[0].title == "1. My section"
    assert cleaned.sections[0].steps[0].title == "Step"
    assert cleaned.sections[0].steps[0].goals == ["g"]


def test_a_plan_title_that_is_only_a_label_is_refused() -> None:
    """LMS-AI-STUDIO: an empty title cannot be created in the LMS."""
    plan = CoursePlanInput(
        sections=[
            PlanSectionInput(title="S1:P1", steps=[PlanStepInput(title="Ok")]),
        ]
    )

    with pytest.raises(BlockInputError):
        clean_plan(plan)


def test_a_stored_plan_that_breaks_the_contract_is_refused() -> None:
    """LMS-AI-STUDIO: the error names the field."""
    with pytest.raises(BlockInputError, match="sections"):
        plan_of({"sections": []})

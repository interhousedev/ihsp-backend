"""LMS-AI-STUDIO: the `lesson_draft` kind (options, schema, task, validation)."""

import dataclasses
from typing import Any
from uuid import uuid4

from app.modules.notebooks.domain.artifacts.handler import ProcessedOutput
from app.modules.notebooks.domain.artifacts.kinds.lesson_draft import HANDLER
from app.modules.notebooks.domain.artifacts.registry import handler_for
from app.modules.notebooks.domain.context import CourseContext
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import InvalidOptionsError, OutputInvalidError
from app.shared.contracts.lms_blocks import StepDraftInput, build_step_content
from tests.notebooks.unit.domain.pack_support import assert_strict, make_ctx, make_pack

import pytest

CTX = make_ctx(make_pack((4,), titles=("Biology 10",)))
LESSON = (
    "### Goal\n\nAfter the lesson you can explain photosynthesis.\n\n"
    "### Light reactions\n\nLight is absorbed by chlorophyll in the thylakoids, "
    "where water is split and oxygen is released.\n\n"
    "### Summary\n\n- Light is the energy source.\n- Sugar is the product."
)


def text(markdown: str = LESSON, **extra: Any) -> dict[str, Any]:
    """A text block of the model's document."""
    return {"type": "text", "markdown": markdown, "refs": ["S1:P1"], **extra}


def single(n: int, **extra: Any) -> dict[str, Any]:
    """A valid single choice question in the model's shape."""
    return {
        "type": "single",
        "prompt": f"Question {n}: what happens in the light reactions?",
        "explanation": "Water is split and oxygen is released.",
        "options": [
            {"text": "Oxygen is released", "correct": True},
            {"text": f"Glucose is built {n}", "correct": False},
            {"text": f"Nitrogen is fixed {n}", "correct": False},
            {"text": f"Starch is stored {n}", "correct": False},
        ],
        **extra,
    }


def quiz_block(*questions: dict[str, Any]) -> dict[str, Any]:
    """A test block of the model's document."""
    return {
        "type": "test",
        "questions": list(questions) or [single(n) for n in range(1, 5)],
        "refs": ["S1:P2"],
    }


def cards(count: int = 6) -> dict[str, Any]:
    """A flashcards block of the model's document."""
    return {
        "type": "flashcards",
        "cards": [
            {"front": f"Term {n}?", "back": f"Definition {n}."} for n in range(count)
        ],
        "refs": ["S1:P3"],
    }


def document(*blocks: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """A valid model document."""
    return {"title": "Light reactions", "blocks": list(blocks) or [text()], **extra}


def run(data: dict[str, Any], ctx: Any = CTX, **options: Any) -> ProcessedOutput:
    parsed = HANDLER.parse_options(options)
    return HANDLER.process(data, parsed, ctx)


def types(result: ProcessedOutput) -> list[str]:
    return [block["type"] for block in result.content["blocks"]]


# - - - Options, schema, task - - -


def test_the_kind_is_registered_with_its_handler() -> None:
    """LMS-AI-STUDIO: the registry finds the lesson handler."""
    assert handler_for(ArtifactKind.LESSON_DRAFT) is HANDLER
    assert HANDLER.schema_name == "nb_lesson_draft"


def test_default_options_are_stored_without_a_step() -> None:
    """LMS-AI-STUDIO: no step id means a new step; defaults are filled."""
    stored = HANDLER.stored_options(HANDLER.parse_options({"topic": " "}))

    assert stored == {
        "include_test": False,
        "include_flashcards": False,
        "length": "standard",
    }


def test_options_keep_the_step_topic_and_extras() -> None:
    """LMS-AI-STUDIO: the design's options."""
    step_id = uuid4()

    stored = HANDLER.stored_options(
        HANDLER.parse_options(
            {
                "step_id": str(step_id),
                "topic": "Light reactions",
                "include_test": True,
                "include_flashcards": True,
                "length": "long",
                "language": "ru",
            }
        )
    )

    assert stored["step_id"] == str(step_id)
    assert stored["length"] == "long" and stored["language"] == "ru"
    assert stored["include_test"] and stored["include_flashcards"]


@pytest.mark.parametrize(
    "options",
    [
        {"length": "epic"},
        {"step_id": "nope"},
        {"topic": "x" * 201},
        {"include_test": 7},
    ],
)
def test_bad_options_are_refused(options: dict[str, Any]) -> None:
    """LMS-AI-STUDIO: invalid options are `InvalidOptionsError`."""
    with pytest.raises(InvalidOptionsError):
        HANDLER.parse_options(options)


def test_the_token_budget_grows_with_length_test_and_cards() -> None:
    """LMS-AI-STUDIO: more is asked, more room is given."""
    plain = HANDLER.max_tokens(HANDLER.parse_options({}))
    long = HANDLER.max_tokens(HANDLER.parse_options({"length": "long"}))
    full = HANDLER.max_tokens(
        HANDLER.parse_options({"include_test": True, "include_flashcards": True})
    )

    assert plain < long
    assert plain < full


def test_strict_schema_is_flat_and_requires_every_property() -> None:
    """LMS-AI-STUDIO: no union, no `$ref`, no `oneOf` in the schema."""
    schema = HANDLER.strict_schema()

    assert_strict(schema)
    assert "oneOf" not in str(schema) and "discriminator" not in str(schema)


def test_task_block_describes_only_the_requested_parts() -> None:
    """LMS-AI-STUDIO: no test and no cards unless asked."""
    plain = HANDLER.task_block(HANDLER.parse_options({"topic": "Photosynthesis"}), None)
    full = HANDLER.task_block(
        HANDLER.parse_options(
            {"include_test": True, "include_flashcards": True, "length": "short"}
        ),
        "focus on oxygen",
    )

    assert "«Photosynthesis»" in plain and "about 600 words" in plain
    assert "Do not add a test block." in plain
    assert "Do not add a flash cards block." in plain
    assert 'Test block (type "test")' in full
    assert "4 questions" in full and "6 cards" in full
    assert "about 300 words" in full and "«focus on oxygen»" in full


def test_default_title_is_the_topic_or_the_notebook() -> None:
    """LMS-AI-STUDIO: shown while the lesson is generated."""
    named = HANDLER.parse_options({"topic": "Light reactions"})
    unnamed = HANDLER.parse_options({})

    assert HANDLER.default_title("Biology", named) == "Light reactions"
    assert HANDLER.default_title("Biology", unnamed) == "Lesson draft: Biology"


# - - - process: the text - - -


def test_a_text_lesson_matches_the_step_draft_contract() -> None:
    """LMS-AI-STUDIO: the content validates as `StepDraftInput` and builds blocks."""
    result = run(document(text()))

    draft = StepDraftInput.model_validate(result.content)
    step = build_step_content(draft)
    assert step["title"] == "Light reactions"
    assert step["blocks"][0]["type"] == "text"
    assert result.content["language"] == "en"
    assert result.content["blocks"][0]["refs"] == ["S1:P1"]
    assert set(result.refs_index) == {"S1:P1"}


def test_labels_html_and_h2_headings_are_cleaned_out_of_the_markdown() -> None:
    """LMS-AI-STUDIO: students never see S1:P1, raw HTML or a ## heading."""
    dirty = LESSON.replace("###", "##") + " Done [[S1:P2]] <b>bold</b>."

    result = run(document(text(dirty)))

    markdown = result.content["blocks"][0]["markdown"]
    assert "S1:P" not in markdown and "<b>" not in markdown
    assert markdown.startswith("### Goal")
    assert "## Goal" not in markdown.replace("### Goal", "")


def test_the_title_is_cleaned_and_falls_back_to_the_topic() -> None:
    """LMS-AI-STUDIO: no numbering in titles; the topic names an untitled lesson."""
    assert run(document(title="Lesson 3: Light")).title == "Light"
    assert run(document(title=" "), topic="Chlorophyll").title == "Chlorophyll"


def test_the_step_title_names_an_untitled_lesson_for_that_step() -> None:
    """LMS-AI-STUDIO: a lesson for a step keeps that step's title by default."""
    course = CourseContext("Biology", "", "outline", step_title="Cells", step_text="x")
    ctx = make_ctx(dataclasses.replace(CTX.pack, course=course))

    assert run(document(title=""), ctx=ctx).title == "Cells"


def test_a_lesson_without_text_asks_for_a_repair() -> None:
    """LMS-AI-STUDIO: cards alone are not a lesson."""
    with pytest.raises(OutputInvalidError) as caught:
        run(document(cards()), include_flashcards=True)

    assert "text block" in " ".join(caught.value.problems)


def test_too_short_a_text_asks_for_a_repair() -> None:
    """LMS-AI-STUDIO: a one-liner is not a lesson."""
    with pytest.raises(OutputInvalidError) as caught:
        run(document(text("### Hi\n\nShort.")))

    assert "too short" in " ".join(caught.value.problems)


@pytest.mark.parametrize("placeholder", ["[insert example here]", "TODO", "{{ name }}"])
def test_a_placeholder_in_the_text_asks_for_a_repair(placeholder: str) -> None:
    """LMS-AI-STUDIO: no "[insert ...]" text is ever published."""
    with pytest.raises(OutputInvalidError) as caught:
        run(document(text(LESSON + f"\n\n{placeholder}")))

    assert "placeholder" in " ".join(caught.value.problems)


def test_a_block_that_is_not_an_object_of_the_schema_is_reported() -> None:
    """LMS-AI-STUDIO: per-block problems name the block."""
    with pytest.raises(OutputInvalidError) as caught:
        run(document({"type": "poem"}))

    assert "block 1" in " ".join(caught.value.problems)


def test_unknown_refs_are_dropped() -> None:
    """LMS-AI-STUDIO: only labels of the pack survive."""
    result = run(document(text(refs=["S9:P9", "S1:P3"])))

    assert result.content["blocks"][0]["refs"] == ["S1:P3"]


# - - - process: the test block - - -


def test_a_requested_test_block_is_built_and_shuffled_by_seed() -> None:
    """LMS-AI-STUDIO: questions pass the LMS rules; the right option is somewhere."""
    result = run(document(text(), quiz_block()), include_test=True)

    assert types(result) == ["text", "test"]
    questions = result.content["blocks"][1]["questions"]
    assert len(questions) == 4
    assert all(sum(o["correct"] for o in q["options"]) == 1 for q in questions)
    positions = {[o["correct"] for o in q["options"]].index(True) for q in questions}
    assert len(positions) > 1  # the seed moved the right answers around
    again = run(document(text(), quiz_block()), include_test=True)
    assert again.content == result.content  # same seed, same shuffle


def test_text_and_number_questions_are_supported() -> None:
    """LMS-AI-STUDIO: the four LMS question types."""
    text_q = {
        "type": "text",
        "prompt": "Which pigment absorbs light?",
        "accepted_answers": ["chlorophyll", " Chlorophyll "],
        "explanation": "Chlorophyll is the green pigment.",
    }
    number_q = {
        "type": "number",
        "prompt": "How many CO2 molecules are used for one glucose?",
        "number": 6,
        "tolerance": 0,
    }
    multiple = single(9, type="multiple")
    multiple["options"][1]["correct"] = True

    result = run(
        document(text(), quiz_block(single(1), single(2), text_q, number_q, multiple)),
        include_test=True,
    )

    questions = result.content["blocks"][1]["questions"]
    assert [q["type"] for q in questions] == [
        "single",
        "single",
        "text",
        "number",
        "multiple",
    ]
    assert questions[3]["number"] == 6
    assert questions[2]["accepted_answers"][0] == "chlorophyll"


@pytest.mark.parametrize(
    "broken",
    [
        {**single(7), "options": [{"text": "Only one", "correct": True}]},
        {
            **single(7),
            "options": [
                {"text": "A", "correct": True},
                {"text": "B", "correct": True},
            ],
        },
        {"type": "text", "prompt": "Name it?"},
        {"type": "number", "prompt": "How many?"},
        {**single(7), "prompt": "TODO write the question"},
    ],
    ids=["one-option", "two-correct", "text-no-answer", "number-no-value", "todo"],
)
def test_a_question_that_breaks_the_lms_rules_is_dropped_and_noted(
    broken: dict[str, Any],
) -> None:
    """LMS-AI-STUDIO: the lesson survives; the note says which question went."""
    questions = [single(1), single(2), single(3), broken]

    result = run(document(text(), quiz_block(*questions)), include_test=True)

    assert len(result.content["blocks"][1]["questions"]) == 3
    assert "test question 4 was dropped" in result.content["notes"][0]


def test_duplicate_questions_and_options_are_merged() -> None:
    """LMS-AI-STUDIO: one question per prompt, one option per text."""
    twin = single(1)
    twin["options"].append({"text": "oxygen is RELEASED", "correct": False})

    result = run(
        document(text(), quiz_block(twin, single(1), single(2), single(3))),
        include_test=True,
    )

    questions = result.content["blocks"][1]["questions"]
    assert len(questions) == 3
    assert all(len(q["options"]) == 4 for q in questions)


def test_too_few_valid_questions_ask_for_a_repair() -> None:
    """LMS-AI-STUDIO: a requested test must have enough questions."""
    broken = {"type": "text", "prompt": "No answer?"}

    with pytest.raises(OutputInvalidError) as caught:
        run(document(text(), quiz_block(single(1), broken)), include_test=True)

    problems = " ".join(caught.value.problems)
    assert "test block" in problems and "dropped" in problems


def test_a_missing_requested_test_asks_for_a_repair() -> None:
    """LMS-AI-STUDIO: include_test without a test block is not accepted."""
    with pytest.raises(OutputInvalidError) as caught:
        run(document(text()), include_test=True)

    assert "test block" in " ".join(caught.value.problems)


def test_a_test_block_nobody_asked_for_is_dropped() -> None:
    """LMS-AI-STUDIO: no test unless include_test."""
    result = run(document(text(), quiz_block()))

    assert types(result) == ["text"]
    assert "not asked for" in result.content["notes"][0]


# - - - process: the flash cards - - -


def test_requested_flash_cards_are_built() -> None:
    """LMS-AI-STUDIO: cards go through the LMS contract; duplicates are merged."""
    deck = cards(7)
    deck["cards"].append({"front": "term 0?", "back": "Again."})
    deck["cards"].append({"front": "", "back": "No front."})

    result = run(document(text(), deck), include_flashcards=True)

    built = result.content["blocks"][1]
    assert built["type"] == "flashcards" and len(built["cards"]) == 7
    assert "card 9 was dropped" in result.content["notes"][0]


def test_too_few_cards_ask_for_a_repair() -> None:
    """LMS-AI-STUDIO: a requested deck must have enough cards."""
    with pytest.raises(OutputInvalidError) as caught:
        run(document(text(), cards(2)), include_flashcards=True)

    assert "flashcards block" in " ".join(caught.value.problems)


def test_the_blocks_keep_the_models_reading_order() -> None:
    """LMS-AI-STUDIO: text, cards, test stay as written."""
    result = run(
        document(text(), cards(), quiz_block()),
        include_flashcards=True,
        include_test=True,
    )

    assert types(result) == ["text", "flashcards", "test"]
    assert set(result.refs_index) == {"S1:P1", "S1:P2", "S1:P3"}

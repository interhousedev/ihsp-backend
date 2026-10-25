"""The exercise kind: options, blueprint, strict schema, validation, grading rules."""

from typing import Any

from app.modules.notebooks.application.export.render import export_as
from app.modules.notebooks.domain.artifacts.handler import (
    ProcessContext,
    ProcessedOutput,
)
from app.modules.notebooks.domain.artifacts.kinds.exercise import HANDLER
from app.modules.notebooks.domain.artifacts.registry import handler_for
from app.modules.notebooks.domain.artifacts.strict import (
    MAX_UNION_PARAMETERS,
    count_unions,
)
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import InvalidOptionsError, OutputInvalidError
from app.modules.notebooks.domain.exercise.answers import (
    copied_run,
    grade_answer,
    normalize_answer,
    text_matches,
)
from app.modules.notebooks.domain.exercise.blueprint import build_blueprint
from tests.notebooks.unit.domain.kinds_b_pack import two_source_pack

import pytest

CTX = ProcessContext(pack=two_source_pack(), language="en", seed=7)
PASSAGE = (
    "A. Plants turn sunlight into chemical energy inside small green bodies. "
    "B. During the first stage, water molecules are broken apart and oxygen "
    "leaves the leaf. C. Later, carbon taken from the air is built into glucose, "
    "which the plant stores as starch."
)


def _q(kind: str, **fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "x",
        "type": kind,
        "prompt": f"Prompt for {kind} {fields.pop('n', '')}",
        "options": [],
        "correct": [],
        "items": [],
        "accepted": [],
        "word_limit": 0,
        "min_words": 0,
        "time_minutes": 0,
        "criteria": [],
        "model_outline": [],
        "explanation": "See paragraph B.",
        "refs": ["S1:P1"],
    }
    return {**base, **fields}


def _choice(kind: str = "single_choice", correct: list[str] | None = None) -> Any:
    options = [{"id": i, "text": f"Answer {i}"} for i in "abcd"]
    return _q(kind, options=options, correct=correct or ["a"])


def _criteria() -> list[dict[str, Any]]:
    return [
        {
            "name": "Task Response (TR)",
            "description": "Answers all parts of the task.",
            "bands": [
                {"band": "9", "descriptor": "Fully addresses all parts."},
                {"band": "5", "descriptor": "Addresses the task only partially."},
            ],
        }
    ]


def run(
    questions: list[dict[str, Any]], stimulus: str = PASSAGE, **options: Any
) -> ProcessedOutput:
    parsed = HANDLER.parse_options(options)
    data = {
        "title": "Practice",
        "instructions": "Read and answer.",
        "sections": [
            {"title": "Passage 1", "stimulus": stimulus, "questions": questions}
        ],
        "rubric": [],
    }
    return HANDLER.process(data, parsed, CTX)


def test_registered_and_defaults() -> None:
    assert handler_for(ArtifactKind.EXERCISE) is HANDLER
    stored = HANDLER.stored_options(HANDLER.parse_options({"exam": "ielts_academic"}))
    assert stored["target_count"] == 13
    assert stored["skill"] == "reading" and stored["mode"] == "auto"
    with pytest.raises(InvalidOptionsError):
        HANDLER.parse_options({"exam": "toefl"})


def test_schema_has_no_nullable_parameter() -> None:
    schema = HANDLER.strict_schema()
    assert count_unions(schema) <= MAX_UNION_PARAMETERS
    assert count_unions(schema) == 0
    question = schema["properties"]["sections"]["items"]["properties"]["questions"]
    assert question["items"]["additionalProperties"] is False


def test_ielts_reading_blueprint() -> None:
    [section] = build_blueprint("ielts_academic", "reading", "auto", 13)
    assert section.words == (700, 900)
    assert section.question_count == 13
    assert len(section.quotas) == 4


def test_sat_and_writing_blueprints() -> None:
    sat = build_blueprint("sat", "reading", "auto", 5)
    assert len(sat) == 5 and all(s.question_count == 1 for s in sat)
    [essay] = build_blueprint("ielts_academic", "writing", "auto", 1)
    assert essay.essay is not None and essay.essay.min_words == 250
    assert len(build_blueprint("ielts_academic", "reading", "full_section", 40)) == 3


def test_budget_grows_with_the_blueprint() -> None:
    small = HANDLER.max_tokens(HANDLER.parse_options({"count": 3}))
    big = HANDLER.max_tokens(
        HANDLER.parse_options(
            {"exam": "ielts_academic", "count": 40, "mode": "full_section"}
        )
    )
    assert small < big <= 32_000


def test_every_type_is_validated_and_numbered() -> None:
    out = run(
        [
            _choice(),
            _choice("multiple_choice", ["a", "b"]),
            _q("true_false_not_given", correct=["Not Given"]),
            _q(
                "matching",
                options=[{"id": "i", "text": "Energy"}, {"id": "ii", "text": "Water"}],
                items=[
                    {"id": "A", "text": "Paragraph A", "answer": "i"},
                    {"id": "B", "text": "Paragraph B", "answer": "ii"},
                ],
            ),
            _q("sentence_completion", accepted=["starch", "Starch."], word_limit=1),
            _q("short_answer", accepted=["oxygen"], word_limit=2),
            _q("essay", criteria=_criteria(), model_outline=["Point"], min_words=250),
        ]
    )
    [section] = out.content["sections"]
    kinds = [q["type"] for q in section["questions"]]
    assert kinds == [
        "single_choice",
        "multiple_choice",
        "true_false_not_given",
        "matching",
        "gap_fill",
        "short_answer",
        "free_response",
    ]
    assert [q["number"] for q in section["questions"]] == list(range(1, 8))
    tfng = section["questions"][2]
    assert tfng["correct"] == ["not_given"] and len(tfng["options"]) == 3
    matching = section["questions"][3]
    assert {item["answer"] for item in matching["items"]} == {"A", "B"}
    assert out.content["total_points"] == 1 + 1 + 1 + 2 + 1 + 1


def test_gap_answer_must_come_from_the_passage() -> None:
    out = run(
        [_choice(), _q("gap_fill", accepted=["photons"], word_limit=1)],
    )
    assert [q["type"] for q in out.content["sections"][0]["questions"]] == [
        "single_choice"
    ]


def test_word_limit_and_broken_choice_are_rejected() -> None:
    with pytest.raises(OutputInvalidError):
        run(
            [
                _q("gap_fill", accepted=["stores as starch"], word_limit=2),
                _choice(correct=["z"]),
            ]
        )


def test_copied_passage_is_rejected() -> None:
    copied = (
        "Light reactions split water and release oxygen. The Calvin cycle fixes "
        "carbon dioxide into sugar. Chlorophyll absorbs light in the thylakoids."
    )
    with pytest.raises(OutputInvalidError) as err:
        run([_choice()], stimulus=copied)
    assert "word for word" in str(err.value.problems)


def test_invalid_openui_block_is_dropped() -> None:
    stimulus = PASSAGE + "\n\n```openui\nroot = Nope(\n```\n"
    out = run([_choice()], stimulus=stimulus)
    assert "openui" not in out.content["sections"][0]["stimulus"]


def test_essay_without_criteria_is_rejected() -> None:
    with pytest.raises(OutputInvalidError):
        run([_q("free_response")], skill="writing")


def test_answer_rules() -> None:
    assert normalize_answer("  The   Starch. ") == "the starch"
    assert text_matches("STARCH", ["starch"], 1)
    assert not text_matches("the starch", ["the starch"], 1)
    assert grade_answer({"type": "single_choice", "correct": ["B"]}, "B") == (1, 1)
    assert grade_answer(
        {"type": "multiple_choice", "correct": ["A", "C"]}, ["C", "A"]
    ) == (1, 1)
    matching = {
        "type": "matching",
        "items": [{"id": "1", "answer": "A"}, {"id": "2", "answer": "B"}],
    }
    assert grade_answer(matching, {"1": "A", "2": "A"}) == (1, 2)
    assert grade_answer({"type": "free_response"}, "text") == (0, 0)
    assert copied_run("one two three four five", ["x one two three four five y"], run=5)


def test_markdown_and_docx_export_have_an_answer_key() -> None:
    out = run([_choice(), _q("gap_fill", accepted=["starch"], word_limit=1)])
    md = export_as(ArtifactKind.EXERCISE, "Practice", out.content, "md")
    text = md.data.decode()
    assert "## Answer key" in text and "starch" in text
    docx = export_as(ArtifactKind.EXERCISE, "Practice", out.content, "docx")
    assert docx.name.endswith(".docx") and docx.data[:2] == b"PK"


def test_feedback_schema_has_no_nullable_parameter() -> None:
    from app.modules.notebooks.domain.exercise.feedback import feedback_schema

    assert count_unions(feedback_schema()) == 0

"""Exam, code and HTML blocks: parsing, server ids and the learner render."""

from typing import Any
from uuid import uuid4

from app.modules.lms.application.learning.get_step_view import widget_block
from app.modules.lms.domain.learning.source_text import export_text
from app.modules.lms.domain.step_content import (
    CodeBlock,
    ExamBlock,
    HtmlBlock,
    StepContent,
    assign_ids,
)
from app.modules.lms.domain.student_render import render_step

import pytest
from pydantic import ValidationError


def _content() -> StepContent:
    return StepContent.model_validate(
        {
            "title": "Practice",
            "blocks": [
                {
                    "type": "exam",
                    "title": "SAT practice",
                    "kind": "sat",
                    "calculator": "graphing",
                    "scaling": {"min_score": 200, "max_score": 800},
                    "sections": [
                        {
                            "title": "Math",
                            "adaptive": True,
                            "modules": [
                                {
                                    "title": "Module 1",
                                    "time_limit_sec": 2100,
                                    "questions": [
                                        {
                                            "type": "single",
                                            "prompt": "2 + 2?",
                                            "explanation": "SECRET_EXPLANATION",
                                            "options": [
                                                {"text": "4", "correct": True},
                                                {"text": "5"},
                                            ],
                                        },
                                        {
                                            "type": "number",
                                            "prompt": "3 * 3?",
                                            "answer": {"value": 9},
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                },
                {
                    "type": "code",
                    "language": "python",
                    "starter": "def f():\n    pass",
                    "solution": "SECRET_SOLUTION",
                    "tests": [
                        {"name": "visible", "code": "assert f() is None"},
                        {"name": "edge", "code": "SECRET_TEST", "hidden": True},
                    ],
                },
                {"type": "html", "title": "Widget", "package_id": str(uuid4())},
            ],
        }
    )


def test_defaults_and_limits() -> None:
    assert CodeBlock().time_limit_ms == 5000
    assert HtmlBlock().height_px == 600
    assert HtmlBlock().entry == "index.html"
    with pytest.raises(ValidationError):
        CodeBlock(time_limit_ms=500)
    with pytest.raises(ValidationError):
        HtmlBlock(height_px=100)
    with pytest.raises(ValidationError):
        HtmlBlock(package_id="not-a-uuid")
    with pytest.raises(ValidationError):
        ExamBlock.model_validate({"sections": [{}] * 7})
    with pytest.raises(ValidationError):
        ExamBlock.model_validate({"sections": [{"modules": [{"time_limit_sec": 30}]}]})
    with pytest.raises(ValidationError):
        ExamBlock.model_validate(
            {
                "sections": [
                    {"modules": [{"questions": [{"type": "sorting", "prompt": "x"}]}]}
                ]
            }
        )
    with pytest.raises(ValidationError):
        ExamBlock.model_validate({"scaling": {"min_score": 800, "max_score": 200}})


def test_assign_ids_reaches_nested_items() -> None:
    content = assign_ids(_content(), set())
    exam, code, html = content.blocks
    assert isinstance(exam, ExamBlock) and isinstance(code, CodeBlock)
    section = exam.sections[0]
    module = section.modules[0]
    question = module.questions[0]
    ids = [
        exam.id,
        section.id,
        module.id,
        question.id,
        *(o.id for o in question.options or []),
        module.questions[1].id,
        code.id,
        *(t.id for t in code.tests),
        html.id,
    ]
    assert all(ids) and len(set(ids)) == len(ids)


def _rendered() -> list[dict[str, Any]]:
    content = assign_ids(_content(), set())
    return list(render_step(content, revision_id="r")["blocks"])


def test_learner_render_strips_answers() -> None:
    exam, code, html = _rendered()
    text = repr(exam) + repr(code)
    for secret in ("SECRET", "correct", "explanation", "answer", "solution"):
        assert secret not in text
    assert exam["sections"][0]["modules"][0]["questions_count"] == 2
    assert exam["scaling"] == {"min_score": 200, "max_score": 800}
    assert [t["code"] for t in code["tests"]] == ["assert f() is None", ""]
    assert [t["name"] for t in code["tests"]] == ["visible", "edge"]
    assert html["height_px"] == 600


def test_learner_views_parse_the_render() -> None:
    exam, code, html = (widget_block(block) for block in _rendered())
    assert exam.type == "exam" and exam.sections[0].adaptive
    assert code.type == "code" and not hasattr(code, "solution")
    assert html.type == "html" and html.entry == "index.html"


def test_source_text_hides_exam_questions_and_secrets() -> None:
    student, _ = export_text(_content())
    assert "2 + 2" not in student and "SECRET" not in student
    assert "Test edge: hidden" in student
    author, _ = export_text(_content(), with_answers=True)
    assert "2 + 2" in author and "SECRET_SOLUTION" in author

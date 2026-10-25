"""Regression: the author tools and Studio content survive the new step types.

The question model grew twelve types and the video block appeared; the tool schemas of
`add_test_block` and `replace_step_content` then carried 22 and 23 nullable fields,
over the 16 a strict provider compiles, so the provider answered HTTP 400 and the
author chat and Studio could not generate. These tests pin the schemas and the
blocks the fake model writes against the LMS block model.
"""

import importlib
import inspect
import pkgutil
from typing import Any

import app.modules.ai.application.tools as tools_pkg
from app.modules.ai.domain.json_schema import strict_tool_parameters
from app.modules.ai.domain.prompts_author import AUTHOR_MARKER
from app.modules.ai.infrastructure.fake_author import author_answer
from app.modules.lms.domain.step_content import StepContent
from app.modules.notebooks.domain.artifacts.strict import (
    MAX_UNION_PARAMETERS,
    count_unions,
)
from app.shared.contracts.lms_blocks import (
    QuestionInput,
    build_block,
    build_test_block,
)

import pytest
from pydantic import BaseModel, TypeAdapter


def _author_args_models() -> list[type[BaseModel]]:
    found: list[type[BaseModel]] = []
    for info in pkgutil.iter_modules(tools_pkg.__path__):
        if not info.name.startswith("lms_"):
            continue
        module = importlib.import_module(f"{tools_pkg.__name__}.{info.name}")
        for name, obj in vars(module).items():
            if (
                inspect.isclass(obj)
                and issubclass(obj, BaseModel)
                and name.endswith("Args")
                and obj.__module__ == module.__name__
            ):
                found.append(obj)
    return found


@pytest.mark.parametrize("model", _author_args_models(), ids=lambda m: m.__name__)
def test_every_author_tool_schema_fits_the_providers_union_limit(
    model: type[BaseModel],
) -> None:
    """No author tool carries more than 16 nullable or union-typed properties."""
    assert count_unions(strict_tool_parameters(model)) <= MAX_UNION_PARAMETERS


ALL_TYPES: list[dict[str, Any]] = [
    {
        "type": "single",
        "prompt": "p",
        "options": [{"text": "a", "correct": True}, {"text": "b"}],
    },
    {
        "type": "multiple",
        "prompt": "p",
        "options": [{"text": "a", "correct": True}, {"text": "b"}],
    },
    {"type": "text", "prompt": "p", "accepted_answers": ["x"]},
    {"type": "number", "prompt": "p", "number": 2},
    {"type": "sorting", "prompt": "p", "items": ["a", "b", "c"]},
    {
        "type": "matching",
        "prompt": "p",
        "pairs": [{"left": "a", "right": "1"}, {"left": "b", "right": "2"}],
    },
    {
        "type": "table",
        "prompt": "p",
        "rows": ["r1", "r2"],
        "columns": ["c1", "c2"],
        "correct_cells": [(0, 1)],
    },
    {"type": "blanks", "prompt": "a {{1}}", "blanks": [{"accepted": ["x"]}]},
    {
        "type": "random_number",
        "prompt": "p",
        "variables": [{"name": "a", "min": 1, "max": 5}],
        "formula": "a*2",
    },
    {"type": "formula", "prompt": "p", "expression": "x+1"},
    {"type": "free", "prompt": "p"},
    {"type": "code", "prompt": "p", "expected_outputs": ["1"]},
]


@pytest.mark.parametrize("raw", ALL_TYPES, ids=lambda r: r["type"])
def test_every_question_type_builds_valid_lms_content(raw: dict[str, Any]) -> None:
    """The built test block is accepted by the LMS step content model."""
    block = build_test_block(None, [QuestionInput.model_validate(raw)])
    content = StepContent.model_validate({"title": "t", "blocks": [block]})
    first = content.blocks[0]
    assert first.questions[0].type == raw["type"]  # type: ignore[union-attr]


def test_a_model_that_writes_empty_values_for_unused_fields_still_builds() -> None:
    """The schema shows optional fields as plain: "" and [] mean "not used"."""
    question = QuestionInput.model_validate(
        {
            "type": "text",
            "prompt": "p",
            "explanation": "",
            "regex": "",
            "options": [],
            "accepted_answers": ["x"],
            "items": [],
            "pairs": [],
            "blanks": [],
            "formula": "",
        }
    )
    built = build_test_block(None, [question])["questions"][0]
    assert built["explanation"] is None
    assert built["answer"]["regex"] is None  # "" would match every answer


def test_a_video_block_is_authorable_and_valid() -> None:
    """The author can write a video block next to text (replace_step_content)."""
    from app.modules.ai.application.tools.lms_replace_step_content import StepBlockArg

    block = TypeAdapter(StepBlockArg).validate_python(
        {"type": "video", "url": "https://youtu.be/abc", "caption": "Intro"}
    )
    built = build_block(block)  # type: ignore[arg-type]
    content = StepContent.model_validate({"title": "t", "blocks": [built]})
    assert content.blocks[0].type == "video"


@pytest.mark.parametrize(
    ("message", "tool"),
    [("write a test", "add_test_block"), ("make flashcards", "add_flashcards_block")],
)
def test_fake_author_calls_validate_against_the_real_tools(
    message: str, tool: str
) -> None:
    """In FAKE mode the scripted tool calls pass the real argument models."""
    step = "0192f0c4-0000-7000-8000-000000000001"
    system = f"{AUTHOR_MARKER}\n[step {step}] Step"
    _, calls = author_answer(system, message)
    assert calls[0]["name"] == tool
    models = {m.__name__: m for m in _author_args_models()}
    args = {
        "add_test_block": "AddTestBlockArgs",
        "add_flashcards_block": "AddFlashcardsBlockArgs",
    }[tool]
    parsed = models[args].model_validate(calls[0]["arguments"])
    assert parsed is not None

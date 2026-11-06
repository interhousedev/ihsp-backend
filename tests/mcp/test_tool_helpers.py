"""MCP: the stand-in for unwired backends and the limits of the test tool inputs."""

from typing import Any

from app.interfaces.mcp.not_wired import NotWired
from app.interfaces.mcp.student import test_inputs as inputs

import pytest
from pydantic import ValidationError


def _question(**fields: Any) -> dict[str, Any]:
    base = {
        "type": "single",
        "prompt": "Which?",
        "options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
        "correct": ["a"],
        "explanation": "Because.",
    }
    return {**base, **fields}


async def test_not_wired_refuses_every_method_and_names_it() -> None:
    """MCP: a missing backend fails when called, never by returning data."""
    backend: Any = NotWired("files")

    with pytest.raises(NotImplementedError, match=r"files\.get_file is not wired"):
        await backend.get_file("x", key="y")


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "essay"},
        {"prompt": ""},
        {"prompt": "x" * 401},
        {"options": []},
        {"options": [{"id": str(i), "text": "t"} for i in range(7)]},
        {"options": [{"id": "a", "text": "t" * 201}]},
        {"options": [{"id": "a" * 21, "text": "t"}]},
        {"correct": []},
        {"explanation": ""},
        {"hint": "h" * 201},
        {"topic": "t" * 61},
    ],
)
def test_new_question_refuses_what_is_over_the_limits(bad: dict[str, Any]) -> None:
    """MCP: the arguments carry the limits of the quiz kind."""
    with pytest.raises(ValidationError):
        inputs.NewQuestion(**_question(**bad))


def test_question_dicts_drop_what_was_left_out() -> None:
    """MCP: a change holds only the fields the caller sent."""
    change = inputs.QuestionChange(id="q1", prompt="New?")

    assert inputs.question_dicts([change]) == [{"id": "q1", "prompt": "New?"}]
    assert "hint" not in inputs.question_dicts([inputs.NewQuestion(**_question())])[0]

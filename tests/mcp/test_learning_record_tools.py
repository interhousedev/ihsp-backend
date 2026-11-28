"""Learning-record MCP tools: scope, marks:read widening, untrusted fields, /app."""

import dataclasses
from typing import Any
from uuid import UUID

from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.mcp.conftest import World
from tests.mcp.helpers import call, data_of, registered_tools, text_of

import pytest

TOOLS = {
    "get_learning_record",
    "get_my_course_progress",
    "list_my_attempts",
    "get_my_attempt",
    "list_my_ai_reviews",
    "get_my_ai_review",
    "list_my_certificates",
    "list_my_badges",
}


class FakeLearning:
    """Returns canned owner data; records the actor of each call."""

    def __init__(self) -> None:
        self.actors: list[UUID] = []

    async def courses(self, actor: Actor) -> list[dict[str, Any]]:
        self.actors.append(actor.user_id)
        return [
            {
                "course_id": str(new_id()),
                "title": "Algebra\x00",
                "progress_pct": 40,
                "certificate": {"tier": "Normal"},
            }
        ]

    async def my_attempt(self, actor: Actor, attempt_id: UUID) -> dict[str, Any]:
        return {
            "attempt_id": str(attempt_id),
            "review_shown": False,
            "questions": [{"question_id": "q1", "correct": True, "prompt": None}],
        }

    async def my_ai_review(self, actor: Actor, session_id: UUID) -> dict[str, Any]:
        return {
            "summary": "ok",
            "scores": [{"name": "a", "score": "3/5", "comment": "c"}],
            "strengths": ["s"],
            "improvements": ["i"],
        }

    async def ai_review_submissions(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []


@pytest.fixture
def fake(world: World, monkeypatch: pytest.MonkeyPatch) -> FakeLearning:
    backend = FakeLearning()
    original = world.deps

    def deps(**kwargs: Any) -> Any:  # noqa: ANN401
        return dataclasses.replace(original(**kwargs), learning_tools=backend)

    monkeypatch.setattr(world, "deps", deps)
    return backend


async def test_tools_are_read_only(world: World) -> None:
    """Every learning-record tool is annotated read-only and non-destructive."""
    tools = {t.name: t for t in await registered_tools(world.deps(), "student")}
    assert TOOLS <= set(tools)
    for name in TOOLS:
        hints = tools[name].annotations
        assert hints is not None and hints.readOnlyHint and not hints.destructiveHint
    lms = {t.name for t in await registered_tools(world.deps(), "lms")}
    assert "list_ai_review_submissions" in lms


async def test_progress_scope_is_required(world: World, fake: FakeLearning) -> None:
    """marks:read alone does not open the record."""
    token, _ = world.connector_token("student", "marks:read")
    async with world.session("student", token) as session:
        result = await call(session, "get_learning_record")
    assert result.isError
    assert "insufficient_scope" in text_of(result)
    assert fake.actors == []


async def test_school_withheld_without_marks_read(
    world: World, fake: FakeLearning
) -> None:
    """The school section names the missing scope; titles are untrusted."""
    token, actor = world.connector_token("student", "progress:read")
    async with world.session("student", token) as session:
        data = data_of(await call(session, "get_learning_record"))
    assert data["school"] == {"withheld": "marks:read"}
    assert data["untrusted_fields"] == ["courses[].title"]
    assert data["certificates_count"] == 1
    assert fake.actors == [actor.user_id]
    assert world.academic_tools.calls == []


async def test_school_given_with_marks_read(world: World, fake: FakeLearning) -> None:
    """With marks:read the platform GPA fills the school section."""
    world.academic_tools.gpa_answer = {"gpa": 4.5, "subjects": []}
    token, _ = world.connector_token("student", "progress:read", "marks:read")
    async with world.session("student", token) as session:
        data = data_of(await call(session, "get_learning_record"))
    assert data["school"]["gpa"] == 4.5


async def test_attempt_and_verdict_mark_untrusted_text(
    world: World, fake: FakeLearning
) -> None:
    """Question and verdict texts are listed as third-party text."""
    token, _ = world.connector_token("student", "progress:read")
    async with world.session("student", token) as session:
        attempt = data_of(
            await call(session, "get_my_attempt", attempt_id=str(new_id()))
        )
        verdict = data_of(
            await call(session, "get_my_ai_review", session_id=str(new_id()))
        )
    assert "questions[].prompt" in attempt["untrusted_fields"]
    assert attempt["questions"][0]["prompt"] is None
    assert {"summary", "strengths[]", "improvements[]"} <= set(
        verdict["untrusted_fields"]
    )


async def test_app_exposes_the_record(world: World, fake: FakeLearning) -> None:
    """The universal server offers student_get_learning_record."""
    token, _ = world.connector_token("app", "student:progress:read")
    async with world.session("app", token) as session:
        data = data_of(await call(session, "student_get_learning_record"))
    assert data["school"] == {"withheld": "marks:read"}

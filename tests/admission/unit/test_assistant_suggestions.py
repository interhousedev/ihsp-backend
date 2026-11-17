"""Suggestion cards of the admission assistant and its AI tools."""

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app.modules.admission.application.assistant import AssistantService
from app.modules.admission.domain.courses import Course
from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.admission import (
    AddSuggestionArgs,
    SuggestArgs,
    make_admission_tools,
)
from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.domain.errors import ToolFailedError
from app.shared.actor import Actor, Role
from app.shared.contracts.admission_assistant import SuggestionCard
from tests.admission.unit.fakes import FakeSources

import pytest

ACTOR = Actor(user_id=uuid4(), roles=frozenset({Role.STUDENT}))


def lms(title: str, provider: str | None = None) -> Course:
    return Course(ACTOR.user_id, "lms", str(uuid4()), title, provider=provider)


def service(sources: FakeSources) -> AssistantService:
    svc = object.__new__(AssistantService)
    svc._sources = sources  # type: ignore[attr-defined]

    async def ctx(actor: Actor) -> Any:
        return SimpleNamespace(actor=actor, user_id=actor.user_id)

    svc._ctx = ctx  # type: ignore[method-assign]
    return svc


async def test_course_cards_skip_enrolled_courses() -> None:
    mine = lms("Algebra")
    sources = FakeSources([], [mine])
    other = lms("Algebra II", "Math dept")
    sources.catalog = [mine, other, lms("Biology")]  # type: ignore[attr-defined]
    cards = await service(sources).suggest(ACTOR, "course", "algebra", 5)
    assert cards == [
        SuggestionCard(
            type="course",
            id=other.source_ref or "",
            title="Algebra II",
            reason="Math dept",
            link=f"/courses/?lms={other.source_ref}",
        )
    ]


async def test_course_cards_respect_the_limit() -> None:
    sources = FakeSources([], [])
    sources.catalog = [lms(f"Course {i}") for i in range(8)]  # type: ignore
    assert len(await service(sources).suggest(ACTOR, "course", "", 3)) == 3


class FakeApi:
    """AdmissionAssistantApi returning one card."""

    card = SuggestionCard("course", "c1", "Algebra II", "Math dept", "/courses/?lms=c1")

    def __init__(self) -> None:
        """No calls yet."""
        self.added: list[tuple[str, str]] = []

    async def suggest(
        self, actor: Actor, kind: str, query: str, limit: int
    ) -> list[SuggestionCard]:
        return [self.card][:limit]

    async def describe(self, actor: Actor, kind: str, item_id: str) -> SuggestionCard:
        return self.card

    async def add_suggestion(
        self, actor: Actor, kind: str, item_id: str
    ) -> SuggestionCard:
        self.added.append((kind, item_id))
        return self.card


def tools(api: Any) -> dict[str, Any]:
    bindings = LateBindings()
    bindings.admission = api
    return {t.name: t for t in make_admission_tools(bindings)}


TOOL_CTX = ToolContext(actor=ACTOR, chat_id=uuid4(), locale="en")


async def test_suggest_tool_returns_cards() -> None:
    out = await tools(FakeApi())["admission_suggest"].run(
        SuggestArgs(kind="course", query="algebra"), TOOL_CTX
    )
    assert out == {
        "cards": [
            {
                "type": "course",
                "id": "c1",
                "title": "Algebra II",
                "reason": "Math dept",
                "link": "/courses/?lms=c1",
            }
        ]
    }


async def test_add_suggestion_needs_approval_and_adds() -> None:
    api = FakeApi()
    tool = tools(api)["admission_add_suggestion"]
    args = AddSuggestionArgs(kind="course", id="c1")
    assert tool.needs_approval
    preview = await tool.preview(args, TOOL_CTX)
    assert preview.title_key == "ai-preview-admission-add-suggestion"
    assert preview.title_params["title"] == "Algebra II"
    out = await tool.run(args, TOOL_CTX)
    assert out["added"]["id"] == "c1" and api.added == [("course", "c1")]


async def test_tools_fail_when_unbound() -> None:
    with pytest.raises(ToolFailedError):
        await tools(None)["admission_suggest"].run(SuggestArgs(kind="course"), TOOL_CTX)

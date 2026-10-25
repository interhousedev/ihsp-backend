"""School facts in a notebook chat without sources: lookup, gap report, safety."""

from typing import Any
from uuid import UUID

from app.modules.notebooks.application.llm import NotebookLlm
from app.modules.notebooks.application.school_knowledge import (
    NOT_FOUND_NOTE,
    SchoolKnowledge,
)
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.contracts.school_knowledge import KnowledgeEntry
from app.shared.ids import new_id
from tests.fakes.ai.knowledge import FakeGapReporter, FakeKnowledgeLookup

ENTRY = KnowledgeEntry("exam-rules", "Exam rules", "No phones.", ("rules",), 1.0)


class _Gateway:
    """Answers the decision round with a scripted tool call (or none)."""

    def __init__(self, query: str | None) -> None:
        self.query = query
        self.requests: list[dict[str, Any]] = []

    async def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(kwargs)
        calls = (
            []
            if self.query is None
            else [
                {
                    "id": "1",
                    "name": "search_knowledge_base",
                    "arguments": {"query": self.query},
                }
            ]
        )
        return {"text": "", "tool_calls": calls, "usage": {}}


def make(
    settings: Settings, query: str | None, hits: list[KnowledgeEntry]
) -> tuple[SchoolKnowledge, FakeKnowledgeLookup, FakeGapReporter, _Gateway]:
    gateway = _Gateway(query)
    lookup, reporter = FakeKnowledgeLookup(hits), FakeGapReporter()
    llm = NotebookLlm(gateway, settings)  # type: ignore[arg-type]
    return SchoolKnowledge(llm, lookup, reporter), lookup, reporter, gateway


def student() -> Actor:
    return Actor(user_id=new_id(), roles=frozenset({Role.STUDENT}))


async def test_hits_become_a_block(settings: Settings) -> None:
    sk, lookup, reporter, _ = make(settings, "exam rules", [ENTRY])

    block = await sk.block_for(
        "What are the exam rules?", notebook_id=new_id(), actor=student()
    )

    assert block is not None and "Exam rules" in block and "No phones." in block
    assert lookup.queries == [("exam rules", 5)] and reporter.reports == []


async def test_no_hits_reports_only_the_query(settings: Settings) -> None:
    sk, _, reporter, _ = make(settings, "chess club head", [])
    notebook_id: UUID = new_id()

    block = await sk.block_for(
        "Who leads chess club?", notebook_id=notebook_id, actor=student()
    )

    assert block == NOT_FOUND_NOTE
    [report] = reporter.reports
    assert report["query"] == "chess club head"
    assert (report["chat_kind"], report["notebook_id"], report["user_role"]) == (
        "notebook",
        notebook_id,
        "student",
    )


async def test_no_tool_call_means_no_lookup(settings: Settings) -> None:
    sk, lookup, reporter, _ = make(settings, None, [ENTRY])

    assert (
        await sk.block_for("What is 2+2?", notebook_id=new_id(), actor=student())
        is None
    )
    assert lookup.queries == [] and reporter.reports == []


async def test_reporter_and_lookup_failures_are_swallowed(settings: Settings) -> None:
    sk, lookup, reporter, _ = make(settings, "x", [])
    reporter.error = RuntimeError("down")
    assert (
        await sk.block_for("q", notebook_id=new_id(), actor=student()) == NOT_FOUND_NOTE
    )

    lookup.error = RuntimeError("down")
    assert await sk.block_for("q", notebook_id=new_id(), actor=student()) is None


async def test_a_student_searches_as_student(settings: Settings) -> None:
    sk, lookup, _, _ = make(settings, "exam rules", [ENTRY])

    await sk.block_for(
        "What are the exam rules?", notebook_id=new_id(), actor=student()
    )

    assert lookup.audiences == ["student"]

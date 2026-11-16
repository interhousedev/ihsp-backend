"""Task suggestions: cleaning of the model's document, consent, ownership, limit."""

import datetime as dt
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.modules.admission.application.tasks_suggest import (
    TaskSuggester,
    clean_suggestions,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    ConsentRequiredError,
)
from app.modules.admission.domain.tasks import SUGGEST_MAX
from app.modules.admission.infrastructure.ai.prompt_source import BuiltinPrompts
from app.modules.admission.infrastructure.ai.prompts import tasks_suggest as prompt
from app.modules.admission.ports.consent import AI
from app.modules.ai.infrastructure.fake_tasks import build_tasks_document
from app.shared.ai_tasks import AiTask
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW, FakeConsents
from tests.fakes.clock import FixedClock

import jsonschema  # type: ignore[import-untyped]
import pytest

USER = new_id()
TODAY = dt.date(2026, 1, 10)


def _task(**kw: Any) -> dict[str, Any]:
    base = {
        "title": "Draft essay",
        "description": "d",
        "priority": "high",
        "deadline": "2026-03-01",
        "steps": [
            {
                "title": "Outline",
                "link_label": "",
                "link_url": "",
                "link_kind": "",
            }
        ],
        "links": [],
    }
    return {**base, **kw}


def test_clean_drops_bad_parts_and_defaults_priority() -> None:
    bad_link = {"label": "x", "url": "javascript:alert(1)", "kind": "external"}
    good = {"label": "Essays", "url": "/essays", "kind": "internal"}
    data = {
        "tasks": [
            _task(priority="urgent", links=[bad_link, good]),
            _task(title="Old", deadline="1999-01-01"),
            _task(title="Past", deadline="2025-01-01"),
            _task(title="draft essay"),
            _task(title="Already open"),
            _task(title=" "),
        ]
    }
    out = clean_suggestions(data, USER, TODAY, {"already open"})
    assert [t.title for t in out] == ["Draft essay", "Old", "Past"]
    first = out[0]
    assert first.priority == "medium" and first.created_by == "ai"
    assert [x.url for x in first.links] == ["/essays"]
    assert out[1].deadline is None and out[2].deadline is None


def test_clean_caps_count() -> None:
    data = {"tasks": [_task(title=f"T{i}") for i in range(SUGGEST_MAX + 5)]}
    assert len(clean_suggestions(data, USER, TODAY, set())) == SUGGEST_MAX


def test_fake_document_is_schema_valid() -> None:
    doc = build_tasks_document(prompt.SCHEMA_NAME)
    assert doc is not None
    jsonschema.validate(doc, prompt.SCHEMA)


class _Empty:
    async def get(self, *a: Any) -> None:
        return None

    async def entries(self, *a: Any) -> list[Any]:
        return []

    async def list_for(self, *a: Any) -> list[Any]:
        return []


class Uow:
    def __init__(self) -> None:
        self.profiles = self.shortlist = self.essays = self.tasks = _Empty()

    async def __aenter__(self) -> "Uow":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class Access:
    def __init__(self, owner: bool = True) -> None:
        self.owner = owner

    async def resolve(self, ctx: Any, student_id: UUID) -> Any:
        return SimpleNamespace(owner=self.owner)


class Ai:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def json(self, **kw: Any) -> tuple[dict[str, Any], str]:
        self.calls.append(kw)
        return build_tasks_document(kw["schema_name"]) or {}, "fake"


class Limiter:
    def __init__(self) -> None:
        self.hits: list[tuple[str, int]] = []

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> None:
        self.hits.append((key, limit))


def _svc(grants: frozenset[str] = frozenset({AI}), owner: bool = True) -> Any:
    ai, limiter = Ai(), Limiter()

    async def weekly(user_id: UUID) -> int | None:
        return 5

    svc = TaskSuggester(
        lambda: Uow(),  # type: ignore[arg-type, return-value]
        Access(owner),  # type: ignore[arg-type]
        ai,
        FakeConsents({USER: grants}),
        limiter,  # type: ignore[arg-type]
        weekly,
        BuiltinPrompts(),
        FixedClock(NOW),
    )
    return svc, ai, limiter


CTX: Any = SimpleNamespace(user_id=USER)


async def test_suggest_returns_unsaved_ai_drafts_and_hits_limit() -> None:
    svc, ai, limiter = _svc()
    out = await svc.suggest(CTX, "en")
    assert out and all(t.created_by == "ai" for t in out)
    assert ai.calls[0]["task"] == AiTask.ADMIT_TASKS_SUGGEST
    assert limiter.hits == [(f"admission:tasks:{USER}", 5)]


async def test_suggest_needs_consent_and_ownership() -> None:
    svc, ai, limiter = _svc(frozenset())
    with pytest.raises(ConsentRequiredError):
        await svc.suggest(CTX, "en")
    svc2, *_ = _svc(owner=False)
    with pytest.raises(AdmissionForbiddenError):
        await svc2.suggest(CTX, "en")
    assert ai.calls == [] and limiter.hits == []

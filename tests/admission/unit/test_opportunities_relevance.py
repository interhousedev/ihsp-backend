"""Opportunities: research kind, study fields and the relevance sort."""

from typing import Any

from app.modules.admission.application import opportunities as mod
from app.modules.admission.application.opportunities import CatalogFilter
from app.modules.admission.application.study_focus import StudyFocus
from app.modules.admission.domain.opportunities import OpportunityDraft
from app.shared.ids import new_id
from tests.admission.unit.fakes_opps import RelevanceEnv
from tests.admission.unit.test_opportunities import _draft

import pytest


def _focus(monkeypatch: pytest.MonkeyPatch, *fields: str) -> None:
    async def load(uow: Any, student_id: Any) -> StudyFocus:
        return StudyFocus(tuple(fields), ())

    monkeypatch.setattr(mod, "load_study_focus", load)


def _env() -> RelevanceEnv:
    e = RelevanceEnv()
    e.publish("Zeta", "computer_science")
    e.publish("Alpha", "information_systems")  # same group (computer_data)
    e.publish("Beta", "law")
    e.publish("Gamma", "computer_science", "law")
    e.publish("Delta")
    return e


def _titles(page: Any) -> list[str]:
    return [o.draft.title for o in page.items]


def test_research_kind_and_study_fields_valid() -> None:
    """ADM-U5-1: research is a valid kind; 8 study fields pass, 9 do not."""
    ok = _draft(new_id(), kind="research", study_field_ids=("physics",) * 8)
    assert ok.problems() == []
    bad = _draft(new_id(), study_field_ids=("physics",) * 9)
    assert "study_field_ids" in bad.problems()


def test_study_field_must_be_canonical() -> None:
    """ADM-U5-2: a free spelling of a field is rejected."""
    bad = _draft(new_id(), study_field_ids=("Computer Science",))
    assert "study_field_ids" in bad.problems()


def test_study_fields_payload_round_trip() -> None:
    """ADM-U5-3: study_field_ids survive to_payload and from_payload."""
    d = _draft(new_id(), study_field_ids=("physics", "law"))
    back = OpportunityDraft.from_payload(d.to_payload())
    assert back.study_field_ids == ("physics", "law")


async def test_relevance_orders_exact_group_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADM-U5-4: exact overlap, then same group, then the rest; nothing hidden."""
    e = _env()
    _focus(monkeypatch, "computer_science")
    page = await e.svc.catalog(CatalogFilter(), await e.student())
    assert page.sort == "relevance"
    assert _titles(page) == ["Gamma", "Zeta", "Alpha", "Beta", "Delta"]
    assert page.total == 5


async def test_for_you_marks_field_and_group_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADM-U5-5: for_you covers field and group matches only."""
    e = _env()
    _focus(monkeypatch, "computer_science")
    page = await e.svc.catalog(CatalogFilter(), await e.student())
    marked = {o.draft.title for o in page.items if o.id in page.for_you}
    assert marked == {"Gamma", "Zeta", "Alpha"}


async def test_explicit_sort_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADM-U5-6: an explicit sort beats the default relevance."""
    e = _env()
    _focus(monkeypatch, "computer_science")
    page = await e.svc.catalog(CatalogFilter(sort="title"), await e.student())
    assert page.sort == "title"
    assert _titles(page) == ["Alpha", "Beta", "Delta", "Gamma", "Zeta"]
    assert page.for_you == frozenset()


async def test_no_fields_defaults_to_title(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADM-U5-7: a student without fields, or staff, gets title order."""
    e = _env()
    _focus(monkeypatch)
    page = await e.svc.catalog(CatalogFilter(), await e.student())
    assert page.sort == "title"
    assert _titles(page)[0] == "Alpha"
    staff = await e.svc.catalog(CatalogFilter(), await e.admin())
    assert staff.sort == "title"


async def test_ranking_happens_before_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADM-U5-8: page 2 continues the relevance order of the whole list."""
    e = _env()
    _focus(monkeypatch, "computer_science")
    ctx = await e.student()
    first = await e.svc.catalog(CatalogFilter(page=1, size=2), ctx)
    second = await e.svc.catalog(CatalogFilter(page=2, size=2), ctx)
    assert _titles(first) == ["Gamma", "Zeta"]
    assert _titles(second) == ["Alpha", "Beta"]
    assert first.total == second.total == 5

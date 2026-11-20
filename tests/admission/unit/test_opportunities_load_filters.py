"""Opportunity filters by delivery, weekly load, cost and start date; plan terms."""

import dataclasses
import datetime as dt
from typing import Any
from uuid import uuid4

from app.modules.admission.application.opportunities import CatalogFilter
from app.modules.admission.domain.opportunities import (
    OpportunityDraft,
    OpportunityMaterial,
    next_start,
)
from app.shared.base_error import ValidationFailedError
from tests.admission.unit.fakes import NOW
from tests.admission.unit.test_opportunities import Env, _draft

import pytest

TODAY = NOW.date()


def _spec(**kw: Any) -> OpportunityDraft:
    return _draft(uuid4(), kind="course", last_year_dates=(), **kw)


async def _publish(e: Env, drafts: dict[str, OpportunityDraft]) -> None:
    """Store published rows directly (an LMS id would need the LMS lookup)."""
    admin = await e.admin()
    for title, d in drafts.items():
        await e.repo.apply(
            dataclasses.replace(d, title=title), target_id=None, by=admin.user_id
        )


async def _titles(e: Env, **kw: Any) -> set[str]:
    page = await e.svc.catalog(CatalogFilter(**kw))
    return {o.draft.title for o in page.items}


def test_delivery_and_hours_validation() -> None:
    lms = _spec(lms_course_id=uuid4())
    material = _spec(
        materials=(OpportunityMaterial("lms_course", "Prep", None, None, uuid4()),)
    )
    assert lms.delivery == "local" and material.delivery == "local"
    assert _spec().delivery == "external"
    assert _spec(hours_per_week=0).problems() == ["hours_per_week"]
    assert _spec(hours_per_week=81).problems() == ["hours_per_week"]
    assert _spec(hours_per_week=6.5).problems() == []


def test_payload_roundtrip_keeps_load_fields() -> None:
    d = _spec(hours_per_week=4.5, starts_on=dt.date(2026, 9, 1), tuition_usd=0)
    back = OpportunityDraft.from_payload(d.to_payload())
    assert (back.hours_per_week, back.starts_on, back.tuition_usd) == (
        4.5,
        dt.date(2026, 9, 1),
        0,
    )
    legacy = d.to_payload()
    del legacy["hours_per_week"], legacy["starts_on"]
    old = OpportunityDraft.from_payload(legacy)
    assert old.hours_per_week is None and old.starts_on is None


def test_next_start_prefers_a_future_start_then_the_next_event() -> None:
    assert next_start(_spec(starts_on=dt.date(2026, 9, 1)), TODAY) == dt.date(
        2026, 9, 1
    )
    past = _spec(starts_on=dt.date(2026, 1, 1), exam_dates=(dt.date(2026, 5, 9),))
    assert next_start(past, TODAY) == dt.date(2026, 5, 9)
    assert next_start(_spec(), TODAY) is None


async def test_filters_by_delivery_cost_hours_and_start() -> None:
    e = Env()
    await _publish(
        e,
        {
            "lms": _spec(
                lms_course_id=uuid4(),
                tuition_usd=0,
                hours_per_week=3,
                starts_on=dt.date(2026, 3, 20),
            ),
            "paid": _spec(
                tuition_usd=300, hours_per_week=10, starts_on=dt.date(2026, 9, 7)
            ),
            "unknown": _spec(),
        },
    )
    assert await _titles(e, delivery="local") == {"lms"}
    assert await _titles(e, delivery="external") == {"paid", "unknown"}
    assert await _titles(e, free=True) == {"lms"}
    assert await _titles(e, max_tuition=500) == {"lms", "paid"}
    assert await _titles(e, max_hours=5) == {"lms"}
    assert await _titles(e, max_hours=10) == {"lms", "paid"}
    assert await _titles(e, starts_within=30) == {"lms"}
    assert await _titles(e, starts_within=365) == {"lms", "paid"}
    assert await _titles(e, starts_month=9) == {"paid"}


async def test_plan_entry_keeps_its_term_and_rejects_unknown_ones() -> None:
    e = Env()
    await _publish(e, {"a": _spec(starts_on=dt.date(2026, 9, 7))})
    oid = next(iter(e.repo.rows))
    st = await e.student()
    saved = await e.svc.save_to_plan(
        st, oid, planned_grade=10, planned_term="summer", note=None
    )
    assert saved.planned_term == "summer"
    view = await e.svc.plan_of(st, st.user_id)
    assert view.analytics.load == {"10:summer": 1}
    with pytest.raises(ValidationFailedError):
        await e.svc.save_to_plan(
            st, oid, planned_grade=10, planned_term="winter", note=None
        )

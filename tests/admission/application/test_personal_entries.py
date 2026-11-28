"""PersonalEntryService over the in-memory opportunity repository."""

import dataclasses
import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.admission.application.personal_entries import PersonalEntryService
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    ItemLimitError,
)
from app.modules.admission.domain.opportunities import MAX_PLAN_ITEMS
from app.modules.admission.domain.personal_entries import (
    PERSONAL_ADD_LIMIT,
    PersonalDraft,
    PlanDuplicateError,
)
from app.shared.actor import Role
from app.shared.base_error import RateLimitedError, ValidationFailedError
from tests.admission.unit.fakes import NOW
from tests.admission.unit.test_access_policy import OTHER, STAFF, STUDENT
from tests.admission.unit.test_opportunities import CountingLimiter, Env, _draft
from tests.fakes.clock import FixedClock

import pytest


class PEnv(Env):
    def __init__(self) -> None:
        super().__init__()
        self.limiter = CountingLimiter()
        self.personal = PersonalEntryService(
            self.uow,  # type: ignore[arg-type]
            self.w.policy,
            self.svc,
            FixedClock(NOW),
            self.limiter,
        )

    async def publish(self, **kw: Any) -> UUID:
        a = await self.admin()
        subj = await self.seed_subject()
        sub = await self.svc.submit(a, _draft(subj, **kw))
        res = await self.svc.review(
            a, sub.id, approve=True, reason=None, lock_version=0
        )
        assert res.applied_id is not None
        return res.applied_id


def _find(**kw: Any) -> PersonalDraft:
    base: dict[str, Any] = {
        "kind": "event",
        "title": "Robotics camp",
        "provider": "Tech Club",
        "url": "https://robots.example.org/camp",
        "registration_deadline": dt.date(2027, 3, 12),
    }
    base.update(kw)
    return PersonalDraft(**base)


async def test_add_lists_and_shows_in_plan() -> None:
    e = PEnv()
    st = await e.student()
    added = await e.personal.add(st, _find(), origin="mcp")
    assert added.entry is not None and added.planned_opportunity_id is None
    assert added.entry.student_id == STUDENT and added.entry.origin == "mcp"
    assert [p.id for p in await e.personal.entries(st)] == [added.entry.id]
    view = await e.svc.plan_of(st, STUDENT)
    assert [p.id for p in view.personal] == [added.entry.id]
    assert view.entries == []
    assert e.limiter.keys == [f"admission:personal_add:{STUDENT}"]


async def test_catalog_match_is_planned_instead() -> None:
    e = PEnv()
    oid = await e.publish()
    st = await e.student()
    added = await e.personal.add(
        st, _find(title="SAT", url="https://www.example.org/sat/", planned_grade=11)
    )
    assert added.entry is None and added.planned_opportunity_id == oid
    view = await e.svc.plan_of(st, STUDENT)
    assert [p.opportunity_id for p in view.entries] == [oid]
    assert view.personal == [] and e.repo.personal == {}


async def test_duplicate_reports_the_existing_entry() -> None:
    e = PEnv()
    st = await e.student()
    first = await e.personal.add(st, _find())
    assert first.entry is not None
    with pytest.raises(PlanDuplicateError) as err:
        await e.personal.add(st, _find(title="ROBOTICS camp!"))
    assert err.value.params == {"entry_id": str(first.entry.id)}


async def test_invalid_fields_are_rejected_before_saving() -> None:
    e = PEnv()
    st = await e.student()
    with pytest.raises(ValidationFailedError) as err:
        await e.personal.add(st, _find(url="http://robots.example.org"))
    assert err.value.params == {"field": "url"}
    assert e.repo.personal == {} and e.limiter.keys == []


async def test_only_the_student_adds_and_staff_cannot() -> None:
    e = PEnv()
    with pytest.raises(AdmissionForbiddenError):
        await e.personal.add(await e.admin(), _find())
    with pytest.raises(AdmissionForbiddenError):
        await e.personal.entries(await e.w.ctx(STAFF, Role.COUNSELOR))


async def test_daily_limit() -> None:
    e = PEnv()
    st = await e.student()
    for i in range(PERSONAL_ADD_LIMIT):
        await e.personal.add(st, _find(title=f"Camp {i}", url=None))
    with pytest.raises(RateLimitedError):
        await e.personal.add(st, _find(title="One more", url=None))


async def test_joint_plan_limit() -> None:
    e = PEnv()
    st = await e.student()
    first = await e.personal.add(st, _find(url=None))
    assert first.entry is not None
    for i in range(MAX_PLAN_ITEMS - 1):
        clone = dataclasses.replace(first.entry, id=UUID(int=i + 1), dedup_key=f"k{i}")
        e.repo.personal[clone.id] = clone
    with pytest.raises(ItemLimitError) as err:
        await e.personal.add(st, _find(title="Sixty-first", url=None))
    assert err.value.params == {"limit": MAX_PLAN_ITEMS}


async def test_update_with_lock_and_foreign_id() -> None:
    e = PEnv()
    st = await e.student()
    added = await e.personal.add(st, _find())
    assert added.entry is not None
    new = await e.personal.update(
        st, added.entry.id, _find(title="Robotics camp 2027"), lock_version=0
    )
    assert new.title == "Robotics camp 2027" and new.lock_version == 1
    with pytest.raises(AdmissionConflictError):
        await e.personal.update(st, added.entry.id, _find(), lock_version=0)
    other = await e.w.ctx(OTHER, Role.STUDENT)
    with pytest.raises(AdmissionNotFoundError):
        await e.personal.update(other, added.entry.id, _find(), lock_version=1)
    with pytest.raises(AdmissionNotFoundError):
        await e.personal.delete(other, added.entry.id)
    await e.personal.delete(st, added.entry.id)
    assert await e.personal.entries(st) == []
    with pytest.raises(AdmissionNotFoundError):
        await e.personal.delete(st, added.entry.id)


async def test_propose_sends_to_moderation_and_reports_status() -> None:
    e = PEnv()
    st = await e.student()
    added = await e.personal.add(st, _find(), propose=True)
    assert added.entry is not None and added.entry.submission_id is not None
    proposals = await e.personal.proposals([added.entry])
    assert proposals[added.entry.id].submission_id == added.entry.submission_id
    assert proposals[added.entry.id].status == "pending"

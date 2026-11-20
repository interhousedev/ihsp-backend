"""Course merge and CourseService."""

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import ResolveAdmissionActor
from app.modules.admission.application.courses import CourseService
from app.modules.admission.domain.courses import Course, merge
from app.modules.admission.domain.errors import AdmissionNotFoundError
from app.modules.admission.ports.consent import NoPurposeConsents
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.admission.unit.fakes import (
    NOW,
    FakeMembership,
    FakeSources,
    FakeStore,
    FakeUow,
    student_ref,
)
from tests.fakes.clock import FixedClock

import pytest

STUDENT = new_id()
LMS_ID = new_id()


def test_merge_keeps_stored_flag_and_refreshes_title() -> None:
    stored = Course(
        STUDENT, "academic", "s1", "Old", grade="4.00", included=False, id=new_id()
    )
    live = [Course(STUDENT, "academic", "s1", "Maths", grade="4.50")]
    snapshot = Course(STUDENT, "lms", "x", "Gone from LMS", id=new_id())
    [a, b] = merge(live, [stored, snapshot])
    assert (a.title, a.grade, a.included, a.id) == ("Maths", "4.50", False, stored.id)
    assert b is snapshot


def _service(store: FakeStore) -> tuple[CourseService, ResolveAdmissionActor]:
    membership = FakeMembership([student_ref(STUDENT, new_id())])
    clock = FixedClock(NOW)
    access = AccessPolicy(
        lambda: FakeUow(store), membership, NoPurposeConsents(), clock, {10, 11}
    )
    sources = FakeSources(
        [Course(STUDENT, "academic", "s1", "Maths")],
        [Course(STUDENT, "lms", str(LMS_ID), "Python", provider="LMS")],
    )
    return (
        CourseService(lambda: FakeUow(store), access, sources),
        ResolveAdmissionActor(lambda: FakeUow(store), membership, clock, {10, 11}),
    )


async def test_owner_flow() -> None:
    store = FakeStore()
    service, resolver = _service(store)
    ctx = await resolver.execute(Actor(STUDENT, frozenset({Role.STUDENT})))
    maths, python = await service.list(ctx, STUDENT)
    assert maths.id is not None and python.id is not None  # LMS is stored too
    assert len(await service.list(ctx, STUDENT)) == 2  # not stored twice
    off = await service.set_included(ctx, maths.id, False)
    assert not off.included
    lms = await service.add_from_lms(ctx, LMS_ID)
    assert (await service.add_from_lms(ctx, LMS_ID)).id == lms.id
    with pytest.raises(AdmissionNotFoundError):
        await service.add_from_lms(ctx, new_id())
    manual = await service.add_manual(
        ctx, Course(STUDENT, "manual", None, "Summer school", year=2025)
    )
    titles = [c.title for c in await service.list(ctx, STUDENT)]
    assert set(titles) == {"Maths", "Python", "Summer school"}
    assert manual.id is not None


async def test_stranger_cannot_edit_or_toggle() -> None:
    store = FakeStore()
    service, resolver = _service(store)
    owner = await resolver.execute(Actor(STUDENT, frozenset({Role.STUDENT})))
    maths, _ = await service.list(owner, STUDENT)
    assert maths.id is not None
    other = await resolver.execute(Actor(new_id(), frozenset({Role.STUDENT})))
    # Another student is a real applicant now; a foreign course stays hidden.
    with pytest.raises(AdmissionNotFoundError):
        await service.set_included(other, maths.id, False)
    with pytest.raises(AdmissionNotFoundError):
        await service.list(other, STUDENT)

"""Mentoring switches: each party sets their own; access needs both."""

from uuid import UUID

from app.modules.admission.application.mentoring import (
    MENTEE_CHANGED,
    MENTOR_CHANGED,
    MentoringService,
)
from app.modules.admission.domain.errors import AdmissionForbiddenError
from app.shared.actor import Role
from tests.admission.unit.fakes import FakeUow
from tests.admission.unit.test_access_policy import STAFF, STUDENT, World, _assign

import pytest


def _service(w: World) -> MentoringService:
    return MentoringService(lambda: FakeUow(w.store))


@pytest.mark.parametrize(
    ("mentee", "mentor", "reaches"),
    [
        (False, False, False),
        (True, False, False),
        (False, True, False),
        (True, True, True),
    ],
)
async def test_access_matrix(mentee: bool, mentor: bool, reaches: bool) -> None:
    w = World()
    w.store.assignments[STAFF] = (_assign("essay_mentor", "student", STUDENT),)
    svc = _service(w)
    await svc.set_mentee(await w.ctx(STUDENT, Role.STUDENT), mentee)
    await svc.set_mentor(await w.ctx(STAFF, Role.MENTOR), mentor)
    ctx = await w.ctx(STAFF, Role.MENTOR)
    assert (await w.policy.resolve(ctx, STUDENT)).in_scope is reaches


async def test_switches_are_audited_and_independent() -> None:
    w = World()
    w.store.assignments[STAFF] = (_assign("essay_mentor", "student", STUDENT),)
    svc = _service(w)
    state = await svc.set_mentee(await w.ctx(STUDENT, Role.STUDENT), True)
    assert state.mentee_opt_in and not state.mentor_opt_in
    state = await svc.set_mentor(await w.ctx(STAFF, Role.MENTOR), True)
    assert state.mentor_opt_in and state.mentor_assignments == 1
    assert w.store.opt_ins[STUDENT].mentee_opt_in
    assert not w.store.opt_ins[STUDENT].mentor_opt_in
    assert [(e.action, e.actor_id) for e in w.store.audit] == [
        (MENTEE_CHANGED, STUDENT),
        (MENTOR_CHANGED, STAFF),
    ]


async def test_mentor_switch_needs_a_mentor_assignment() -> None:
    w = World()
    other: UUID = STAFF
    with pytest.raises(AdmissionForbiddenError):
        await _service(w).set_mentor(await w.ctx(other, Role.MENTOR), True)
    assert not w.store.opt_ins and not w.store.audit


async def test_mentee_switch_is_for_applicants_only() -> None:
    w = World()
    with pytest.raises(AdmissionForbiddenError):
        await _service(w).set_mentee(await w.ctx(STAFF, Role.MENTOR), True)
    assert not w.store.opt_ins

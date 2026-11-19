"""Student-side gate: applicants need the student role (alumni excepted)."""

import datetime as dt
from uuid import UUID

from app.interfaces.http.v1.admission.deps import require_applicant
from app.modules.admission.application.actor import ResolveAdmissionActor
from app.modules.admission.domain.access import Entitlement
from app.modules.admission.domain.errors import NotApplicantError
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.admission.unit.fakes import (
    NOW,
    FakeMembership,
    FakeStore,
    FakeUow,
    student_ref,
)
from tests.fakes.clock import FixedClock

import pytest

COUNSELOR = new_id()
GROUP = new_id()


def _resolver(store: FakeStore, membership: FakeMembership) -> ResolveAdmissionActor:
    return ResolveAdmissionActor(
        lambda: FakeUow(store), membership, FixedClock(NOW), {10, 11}
    )


def _row(user_id: UUID, kind: str) -> Entitlement:
    return Entitlement(user_id, kind, None, None, NOW)  # type: ignore[arg-type]


async def test_counselor_without_student_role_is_refused_student_side() -> None:
    store = FakeStore()
    resolver = _resolver(store, FakeMembership([]))
    ctx = await resolver.execute(Actor(COUNSELOR, frozenset({Role.COUNSELOR})))
    assert ctx.admission.kind == "staff" and ctx.admission.may_enter
    with pytest.raises(NotApplicantError):
        await require_applicant(ctx)


async def test_counselor_with_student_role_passes_both_sides() -> None:
    store = FakeStore()
    membership = FakeMembership([student_ref(COUNSELOR, GROUP, "11-A")])
    ctx = await _resolver(store, membership).execute(
        Actor(COUNSELOR, frozenset({Role.COUNSELOR, Role.STUDENT}))
    )
    assert ctx.admission.kind == "applicant"
    assert ctx.admission.is_staff and ctx.admission.may_enter
    assert await require_applicant(ctx) is ctx


async def test_stored_school_student_row_needs_student_role() -> None:
    store = FakeStore()
    store.entitlements[COUNSELOR] = _row(COUNSELOR, "school_student")
    ctx = await _resolver(store, FakeMembership([])).execute(
        Actor(COUNSELOR, frozenset({Role.COUNSELOR}))
    )
    assert not ctx.admission.is_applicant
    with pytest.raises(NotApplicantError):
        await require_applicant(ctx)


async def test_alumni_row_needs_no_student_role() -> None:
    store = FakeStore()
    store.entitlements[COUNSELOR] = _row(COUNSELOR, "alumni")
    ctx = await _resolver(store, FakeMembership([])).execute(
        Actor(COUNSELOR, frozenset({Role.COUNSELOR}))
    )
    assert ctx.admission.is_applicant
    assert await require_applicant(ctx) is ctx


def test_revoked_row_is_not_an_applicant() -> None:
    from app.modules.admission.domain.entitlement import AdmissionActor

    revoked = Entitlement(
        COUNSELOR, "alumni", None, None, NOW, revoked_at=NOW + dt.timedelta(days=1)
    )
    actor = AdmissionActor(COUNSELOR, revoked, frozenset(), student_role=True)
    assert not actor.is_applicant

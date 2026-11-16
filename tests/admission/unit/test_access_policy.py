"""AccessPolicy: owner, counselor scopes, mentor opt-in, consent, helper, audit."""

import datetime as dt
from uuid import UUID

from app.modules.admission.application.access import VIEWED, AccessPolicy
from app.modules.admission.application.actor import (
    AdmissionContext,
    ResolveAdmissionActor,
)
from app.modules.admission.domain.access import Assignment, StaffRole
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.permissions import BUILTIN_ROLES, Permission
from app.modules.admission.ports.consent import STAFF_VIEW
from app.modules.admission.ports.repositories import OptIns
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.admission.unit.fakes import (
    NOW,
    FakeConsents,
    FakeMembership,
    FakeStore,
    FakeUow,
    student_ref,
)
from tests.fakes.clock import FixedClock

import pytest

STUDENT = new_id()
OTHER = new_id()
GROUP = new_id()
OTHER_GROUP = new_id()
STAFF = new_id()


def _role(key: str) -> StaffRole:
    b = next(r for r in BUILTIN_ROLES if r.key == key)
    return StaffRole(
        id=new_id(),
        kind=b.kind,
        name=b.names[2],
        name_i18n={},
        permissions=frozenset(b.permissions),
        is_builtin=True,
    )


def _assign(
    key: str, scope: str, ref: UUID | None, expires: dt.datetime | None = None
) -> Assignment:
    return Assignment(
        id=new_id(),
        user_id=STAFF,
        role=_role(key),
        scope_kind=scope,  # type: ignore[arg-type]
        scope_ref=ref,
        starts_at=NOW - dt.timedelta(days=1),
        expires_at=expires,
        granted_by=None,
    )


class World:
    def __init__(self, consent: bool = True) -> None:
        self.store = FakeStore()
        self.membership = FakeMembership(
            [student_ref(STUDENT, GROUP), student_ref(OTHER, OTHER_GROUP)]
        )
        granted = {STUDENT: frozenset({STAFF_VIEW}), OTHER: frozenset({STAFF_VIEW})}
        self.policy = AccessPolicy(
            lambda: FakeUow(self.store),
            self.membership,
            FakeConsents(granted if consent else {}),
            FixedClock(NOW),
            {10, 11},
        )
        self.resolver = ResolveAdmissionActor(
            lambda: FakeUow(self.store), self.membership, FixedClock(NOW), {10, 11}
        )

    async def ctx(self, user_id: UUID, *roles: Role) -> AdmissionContext:
        return await self.resolver.execute(Actor(user_id, frozenset(roles)))


async def test_owner_reads_without_audit() -> None:
    w = World()
    ctx = await w.ctx(STUDENT, Role.STUDENT)
    res = await w.policy.require(ctx, STUDENT, Permission.PROFILE_READ)
    assert res.owner
    assert w.store.audit == []


async def test_counselor_all_reads_and_is_audited() -> None:
    w = World()
    a = _assign("counselor_full", "all", None)
    w.store.assignments[STAFF] = (a,)
    ctx = await w.ctx(STAFF, Role.COUNSELOR)
    res = await w.policy.require(ctx, OTHER, Permission.PROFILE_READ)
    assert not res.owner and not res.limited
    [event] = w.store.audit
    assert event.action == VIEWED and event.student_id == OTHER
    assert event.staff_role_id == a.role.id
    assert event.meta == {"permission": "profile:read", "limited": False}


async def test_cohort_scope_hides_other_groups() -> None:
    w = World()
    w.store.assignments[STAFF] = (_assign("counselor_full", "cohort", GROUP),)
    ctx = await w.ctx(STAFF, Role.COUNSELOR)
    await w.policy.require(ctx, STUDENT, Permission.PROFILE_READ)
    with pytest.raises(AdmissionNotFoundError):
        await w.policy.require(ctx, OTHER, Permission.PROFILE_READ)
    assert sorted(await w.policy.students_in_scope(ctx) or []) == [STUDENT]


async def test_student_scope_and_everyone_scope_listing() -> None:
    w = World()
    w.store.assignments[STAFF] = (_assign("counselor_full", "student", OTHER),)
    ctx = await w.ctx(STAFF, Role.COUNSELOR)
    assert await w.policy.students_in_scope(ctx) == [OTHER]
    w.store.assignments[STAFF] = (_assign("counselor_full", "all", None),)
    assert await w.policy.students_in_scope(await w.ctx(STAFF, Role.COUNSELOR)) is None


async def test_assignment_needs_global_role_and_live_window() -> None:
    w = World()
    w.store.assignments[STAFF] = (_assign("counselor_full", "all", None),)
    with pytest.raises(AdmissionNotFoundError):
        await w.policy.require(await w.ctx(STAFF), OTHER, Permission.PROFILE_READ)
    expired = _assign("counselor_full", "all", None, NOW - dt.timedelta(minutes=1))
    w.store.assignments[STAFF] = (expired,)
    with pytest.raises(AdmissionNotFoundError):
        await w.policy.require(
            await w.ctx(STAFF, Role.COUNSELOR), OTHER, Permission.PROFILE_READ
        )


async def test_mentor_needs_both_opt_ins() -> None:
    w = World()
    w.store.assignments[STAFF] = (_assign("essay_mentor", "student", STUDENT),)
    w.store.opt_ins[STAFF] = OptIns(mentee_opt_in=False, mentor_opt_in=True)
    ctx = await w.ctx(STAFF, Role.MENTOR)
    assert not (await w.policy.resolve(ctx, STUDENT)).in_scope
    w.store.opt_ins[STUDENT] = OptIns(mentee_opt_in=True, mentor_opt_in=False)
    assert (await w.policy.resolve(ctx, STUDENT)).in_scope


async def test_no_consent_limits_to_403() -> None:
    w = World(consent=False)
    w.store.assignments[STAFF] = (_assign("counselor_full", "all", None),)
    ctx = await w.ctx(STAFF, Role.COUNSELOR)
    res = await w.policy.resolve(ctx, STUDENT)
    assert res.in_scope and res.limited
    with pytest.raises(AdmissionForbiddenError):
        await w.policy.require(ctx, STUDENT, Permission.PROFILE_READ)
    assert w.store.audit == []


async def test_helper_reaches_only_helped_student() -> None:
    w = World()
    w.store.helpers[STAFF] = frozenset({STUDENT})
    ctx = await w.ctx(STAFF)
    assert ctx.admission.helper_only
    await w.policy.require(ctx, STUDENT, Permission.HELP_RESPOND)
    with pytest.raises(AdmissionForbiddenError):
        await w.policy.require(ctx, STUDENT, Permission.PROFILE_READ)
    with pytest.raises(AdmissionNotFoundError):
        await w.policy.require(ctx, OTHER, Permission.HELP_RESPOND)
    assert w.policy.scope(ctx).student_ids == frozenset({STUDENT})

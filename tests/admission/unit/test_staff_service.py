"""Staff caseload, delegation, comments and saved views."""

import datetime as dt
from uuid import UUID

from app.modules.admission.application.comments import CommentService
from app.modules.admission.application.staff import CaseloadFilters, StaffService
from app.modules.admission.domain.access import Assignment, StaffRole
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    DelegationDeniedError,
    SavedViewLimitError,
)
from app.modules.admission.domain.permissions import BUILTIN_ROLES
from app.modules.admission.domain.staff import MAX_SAVED_VIEWS, CaseloadRow, StaffUser
from app.modules.admission.ports.repositories import OptIns
from app.shared.actor import Role
from app.shared.base_error import ValidationFailedError
from app.shared.contracts.identity import UserRef, UserStatus
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW, FakeDirectory
from tests.admission.unit.test_access_policy import (
    GROUP,
    OTHER,
    OTHER_GROUP,
    STAFF,
    STUDENT,
    World,
    _assign,
)
from tests.fakes.clock import FixedClock

import pytest

TARGET = new_id()


def _builtin(key: str) -> StaffRole:
    b = next(r for r in BUILTIN_ROLES if r.key == key)
    return StaffRole(
        id=new_id(),
        kind=b.kind,
        name=b.names[2],
        name_i18n={},
        permissions=frozenset(b.permissions),
        is_builtin=True,
    )


def comments(w: World) -> CommentService:
    from tests.admission.unit.fakes import FakeUow

    return CommentService(lambda: FakeUow(w.store), w.policy, FixedClock(NOW))


def _service(w: World, directory: FakeDirectory | None = None) -> StaffService:
    from tests.admission.unit.fakes import FakeUow

    return StaffService(
        lambda: FakeUow(w.store),
        w.policy,
        w.membership,
        directory or FakeDirectory([StaffUser(TARGET, frozenset({"counselor"}), True)]),
        FixedClock(NOW),
    )


def _row(student: UUID, stage: str = "applying", overdue: int = 0) -> CaseloadRow:
    return CaseloadRow(student, stage, NOW + dt.timedelta(days=3), overdue, 1)


async def test_caseload_scope_and_filters() -> None:
    w = World()
    w.store.assignments[STAFF] = (_assign("counselor_full", "cohort", GROUP),)
    w.store.caseload_rows = [_row(STUDENT, overdue=2), _row(OTHER)]
    ctx = await w.ctx(STAFF, Role.COUNSELOR)
    items = await _service(w).caseload(ctx, CaseloadFilters())
    assert [i.row.student_id for i in items] == [STUDENT]
    assert items[0].row.group_name == "11-A"
    assert await _service(w).caseload(ctx, CaseloadFilters(risk=True))
    assert not await _service(w).caseload(ctx, CaseloadFilters(stage="other"))
    assert not await _service(w).caseload(ctx, CaseloadFilters(group_id=OTHER_GROUP))


class _Names:
    async def get_users(self, ids: list[UUID]) -> dict[UUID, UserRef]:
        return {
            i: UserRef(
                i,
                None,
                "Ali",
                "Karimov",
                None,
                frozenset({Role.STUDENT}),
                UserStatus.ACTIVE,
                "en",
                None,
            )
            for i in ids
        }


async def test_caseload_carries_student_names() -> None:
    w = World()
    w.store.assignments[STAFF] = (_assign("counselor_full", "cohort", GROUP),)
    w.store.caseload_rows = [_row(STUDENT)]
    ctx = await w.ctx(STAFF, Role.COUNSELOR)
    svc = _service(w)
    svc._identity = _Names()  # type: ignore[assignment]
    [item] = await svc.caseload(ctx, CaseloadFilters())
    assert item.student_name == "Karimov Ali"


async def test_caseload_without_scope_is_forbidden() -> None:
    w = World()
    ctx = await w.ctx(STAFF, Role.COUNSELOR)
    with pytest.raises(AdmissionForbiddenError):
        await _service(w).caseload(ctx, CaseloadFilters())


def _grantor(w: World, *, role_key: str = "counselor_full", scope: str = "all") -> None:
    ref = None if scope == "all" else STUDENT
    parent = _assign("counselor_full", scope, ref)
    w.store.assignments[STAFF] = (parent,)


def _child_role(w: World, key: str = "counselor_documents") -> StaffRole:
    role = _builtin(key)
    w.store.roles[role.id] = role
    return role


async def _delegate(w: World, role: StaffRole, **kw: object) -> Assignment:
    args: dict[str, object] = {
        "user_id": TARGET,
        "staff_role_id": role.id,
        "scope_kind": "student",
        "scope_ref": STUDENT,
        "expires_at": None,
    }
    args.update(kw)
    ctx = await w.ctx(STAFF, Role.COUNSELOR)
    return await _service(w).assign(ctx, **args)  # type: ignore[arg-type]


async def test_delegation_creates_child_of_parent() -> None:
    w = World()
    _grantor(w)
    role = _child_role(w)
    created = await _delegate(w, role)
    assert created.granted_by == STAFF and created.granted_via == "delegation"
    assert created.parent_assignment_id == w.store.assignments[STAFF][0].id


@pytest.mark.parametrize(
    ("kw", "reason"),
    [
        ({"user_id": STAFF}, "target"),
        ({"user_id": new_id()}, "target"),
        ({"scope_kind": "all", "scope_ref": None}, "scope"),
        ({"expires_at": NOW - dt.timedelta(days=1)}, "expiry"),
    ],
)
async def test_delegation_denials(kw: dict[str, object], reason: str) -> None:
    w = World()
    _grantor(w)
    role = _child_role(w)
    with pytest.raises(DelegationDeniedError) as e:
        await _delegate(w, role, **kw)
    assert e.value.params["reason"] == reason


async def test_delegation_target_must_hold_global_role() -> None:
    w = World()
    _grantor(w)
    role = _child_role(w)
    directory = FakeDirectory([StaffUser(TARGET, frozenset({"student"}), True)])
    ctx = await w.ctx(STAFF, Role.COUNSELOR)
    with pytest.raises(DelegationDeniedError) as e:
        await _service(w, directory).assign(
            ctx,
            user_id=TARGET,
            staff_role_id=role.id,
            scope_kind="student",
            scope_ref=STUDENT,
            expires_at=None,
        )
    assert e.value.params["reason"] == "global_role"


async def test_delegation_out_of_scope_student_is_404() -> None:
    w = World()
    _grantor(w, scope="student")
    role = _child_role(w)
    with pytest.raises(AdmissionNotFoundError):
        await _delegate(w, role, scope_ref=OTHER)


async def test_delegation_expiry_may_not_exceed_parent() -> None:
    w = World()
    parent = _assign("counselor_full", "all", None, expires=NOW + dt.timedelta(days=5))
    w.store.assignments[STAFF] = (parent,)
    role = _child_role(w)
    with pytest.raises(DelegationDeniedError) as e:
        await _delegate(w, role, expires_at=NOW + dt.timedelta(days=9))
    assert e.value.params["reason"] == "expiry"
    await _delegate(w, role, expires_at=NOW + dt.timedelta(days=2))


async def test_staff_without_assign_permission_is_forbidden() -> None:
    w = World()
    w.store.assignments[STAFF] = (_assign("counselor_documents", "all", None),)
    role = _child_role(w)
    with pytest.raises(AdmissionForbiddenError):
        await _delegate(w, role)


async def test_revoke_only_own_delegation() -> None:
    w = World()
    _grantor(w)
    role = _child_role(w)
    created = await _delegate(w, role)
    ctx = await w.ctx(STAFF, Role.COUNSELOR)
    stranger = await w.ctx(OTHER, Role.COUNSELOR)
    with pytest.raises(AdmissionNotFoundError):
        await _service(w).revoke(stranger, created.id)
    await _service(w).revoke(ctx, created.id)
    assert w.store.assignment_rows[created.id].revoked_at == NOW


async def test_mentor_needs_opt_in() -> None:
    w = World()
    _grantor(w)
    role = _child_role(w, "student_counselor")
    directory = FakeDirectory([StaffUser(TARGET, frozenset({"mentor"}), True)])
    ctx = await w.ctx(STAFF, Role.COUNSELOR)
    args = {
        "user_id": TARGET,
        "staff_role_id": role.id,
        "scope_kind": "student",
        "scope_ref": STUDENT,
        "expires_at": None,
    }
    with pytest.raises(DelegationDeniedError):
        await _service(w, directory).assign(ctx, **args)  # type: ignore[arg-type]
    w.store.opt_ins[TARGET] = OptIns(False, True)
    w.store.opt_ins[STUDENT] = OptIns(True, False)
    await _service(w, directory).assign(ctx, **args)  # type: ignore[arg-type]


async def test_saved_views_limit_validation_and_ownership() -> None:
    w = World()
    ctx = await w.ctx(STAFF, Role.COUNSELOR)
    other = await w.ctx(OTHER, Role.COUNSELOR)
    svc = _service(w)
    view = await svc.add_view(ctx, " Risk ", {"risk": True}, None, False)
    assert view.name == "Risk"
    with pytest.raises(ValidationFailedError):
        await svc.add_view(ctx, "x", {"bogus": 1}, None, False)
    with pytest.raises(ValidationFailedError):
        await svc.add_view(ctx, " ", {}, None, False)
    with pytest.raises(AdmissionNotFoundError):
        await svc.update_view(
            other,
            view.id,
            name="n",
            filters={},
            sort=None,
            is_default=False,
            lock_version=1,
        )
    with pytest.raises(AdmissionNotFoundError):
        await svc.delete_view(other, view.id)
    for _ in range(MAX_SAVED_VIEWS - 1):
        await svc.add_view(ctx, "v", {}, None, False)
    with pytest.raises(SavedViewLimitError):
        await svc.add_view(ctx, "v", {}, None, False)
    await svc.delete_view(ctx, view.id)


async def test_comment_visibility_rules() -> None:
    w = World()
    w.store.assignments[STAFF] = (_assign("counselor_full", "all", None),)
    staff = await w.ctx(STAFF, Role.COUNSELOR)
    owner = await w.ctx(STUDENT, Role.STUDENT)
    svc = comments(w)
    target = new_id()
    shown = await svc.add(staff, STUDENT, "profile", target, "hello")
    hidden = await svc.add(
        staff, STUDENT, "profile", target, "note", visibility="staff_only"
    )
    assert [d.user_id for d in w.store.notifications] == [STUDENT]
    assert {c.id for c in await svc.thread(staff, STUDENT, "profile", target)} == {
        shown.id,
        hidden.id,
    }
    assert [c.id for c in await svc.thread(owner, STUDENT, "profile", target)] == [
        shown.id
    ]
    assert [c.id for c in await svc.inbox(owner)] == [shown.id]
    with pytest.raises(AdmissionForbiddenError):
        await svc.add(owner, STUDENT, "profile", target, "x", visibility="staff_only")
    # the owner may delete a student-visible comment, not a staff note
    with pytest.raises(AdmissionNotFoundError):
        await svc.delete(owner, hidden.id)
    await svc.delete(owner, shown.id)


async def test_comment_scope_and_deletion_are_idor_safe() -> None:
    w = World()
    w.store.assignments[STAFF] = (_assign("counselor_full", "cohort", GROUP),)
    staff = await w.ctx(STAFF, Role.COUNSELOR)
    stranger = await w.ctx(OTHER, Role.STUDENT)
    svc = comments(w)
    target = new_id()
    with pytest.raises(AdmissionNotFoundError):
        await svc.add(staff, OTHER, "profile", target, "x")
    with pytest.raises(AdmissionNotFoundError):
        await svc.thread(stranger, STUDENT, "profile", target)
    c = await svc.add(staff, STUDENT, "profile", target, "x")
    with pytest.raises(AdmissionNotFoundError):
        await svc.delete(stranger, c.id)
    with pytest.raises(AdmissionNotFoundError):
        await svc.add(staff, STUDENT, "unknown", target, "x")


async def test_comment_staff_role_without_scope_is_404() -> None:
    w = World()
    svc = comments(w)
    ctx = await w.ctx(STAFF, Role.COUNSELOR)
    with pytest.raises(AdmissionNotFoundError):
        await svc.add(ctx, STUDENT, "profile", new_id(), "x")


async def test_revoke_by_parent_holder_requires_active_parent() -> None:
    import dataclasses

    w = World()
    _grantor(w)
    role = _child_role(w)
    created = await _delegate(w, role)
    ctx = await w.ctx(STAFF, Role.COUNSELOR)
    parent = created.parent_assignment_id
    expired = tuple(
        dataclasses.replace(a, revoked_at=NOW) if a.id == parent else a
        for a in ctx.assignments
    )
    holder = dataclasses.replace(
        await w.ctx(OTHER, Role.COUNSELOR), assignments=expired
    )
    with pytest.raises(AdmissionNotFoundError):
        await _service(w).revoke(holder, created.id)


class _Search:
    def __init__(self, users: list[UserRef]) -> None:
        self.users = users
        self.roles: tuple[Role, ...] = ()

    async def search_users(
        self, query: str, *, roles: tuple[Role, ...] = (), limit: int = 20
    ) -> list[UserRef]:
        self.roles = tuple(roles)
        return self.users


def _ref(role: Role, status: UserStatus = UserStatus.ACTIVE) -> UserRef:
    return UserRef(
        new_id(), "x", "Ali", "Staff", None, frozenset({role}), status, "en", None
    )


async def test_assignable_users_are_active_staff_scoped_to_assigners() -> None:
    w = World()
    w.store.assignments[STAFF] = (_assign("counselor_full", "all", None),)
    ctx = await w.ctx(STAFF, Role.COUNSELOR)
    active, blocked = _ref(Role.MENTOR), _ref(Role.MENTOR, UserStatus.BLOCKED)
    svc = _service(w)
    search = _Search([active, blocked])
    svc._identity = search  # type: ignore[assignment]
    found = await svc.assignable_users(ctx, STUDENT, "ali")
    assert [u.id for u in found] == [active.id]
    assert Role.STUDENT not in search.roles
    assert Role.MENTOR in search.roles


async def test_assignable_users_denied_out_of_scope() -> None:
    w = World()
    ctx = await w.ctx(OTHER, Role.COUNSELOR)
    with pytest.raises(AdmissionNotFoundError):
        await _service(w).assignable_users(ctx, STUDENT, "")


async def test_admin_enters_with_an_empty_caseload() -> None:
    w = World()
    ctx = await w.ctx(new_id(), Role.ADMIN)
    assert ctx.admission.may_enter and ctx.admission.is_staff
    assert await _service(w).caseload(ctx, CaseloadFilters()) == []

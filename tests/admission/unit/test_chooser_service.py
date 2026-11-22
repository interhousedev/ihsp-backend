"""Chooser services: list rules, estimate visibility, sign-off and audit."""

import datetime as dt
from decimal import Decimal
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import (
    AdmissionContext,
    ResolveAdmissionActor,
)
from app.modules.admission.application.chooser import CatalogService, ListService
from app.modules.admission.application.runtime_settings import RuntimeSettingsService
from app.modules.admission.domain.access import Assignment, StaffRole
from app.modules.admission.domain.chooser import (
    CatalogFilters,
    CatalogInstitution,
    FactView,
)
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    AffordabilityGateError,
)
from app.modules.admission.domain.permissions import BUILTIN_ROLES
from app.modules.admission.domain.runtime_settings import ESTIMATES_STUDENT_VISIBLE
from app.modules.admission.ports.consent import STAFF_VIEW
from app.settings_admission import AdmissionSettings
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
from tests.admission.unit.fakes_documents import FakeIdentity
from tests.fakes.clock import FixedClock

import pytest

STUDENT, STAFF, GROUP, LONER = new_id(), new_id(), new_id(), new_id()


def _counselor() -> Assignment:
    b = next(r for r in BUILTIN_ROLES if r.key == "counselor_full")
    role = StaffRole(
        id=new_id(),
        kind=b.kind,
        name=b.names[2],
        name_i18n={},
        permissions=frozenset(b.permissions),
        is_builtin=True,
    )
    return Assignment(
        id=new_id(),
        user_id=STAFF,
        role=role,
        scope_kind="all",
        scope_ref=None,
        starts_at=NOW - dt.timedelta(days=1),
        expires_at=None,
        granted_by=None,
    )


class World:
    def __init__(self) -> None:
        self.store = FakeStore()
        factory = lambda: FakeUow(self.store)  # noqa: E731
        membership = FakeMembership([student_ref(STUDENT, GROUP)])
        clock = FixedClock(NOW)
        self.consents = FakeConsents({STUDENT: frozenset({STAFF_VIEW})})
        self.identity = FakeIdentity({}, {Role.COUNSELOR: [STAFF, LONER]})
        access = AccessPolicy(
            factory,
            membership,
            self.consents,
            clock,
            {10, 11},
        )
        self.resolver = ResolveAdmissionActor(factory, membership, clock, {10, 11})
        self.lists = ListService(
            factory,
            access,
            RuntimeSettingsService(factory, ttl=0),
            AdmissionSettings(),
            clock,
            self.identity,  # type: ignore[arg-type]
        )
        self.catalog = CatalogService(factory)
        self.store.assignments[STAFF] = (_counselor(),)
        self.store.budget_bands[STUDENT] = "5k_15k"

    def inst(self, name: str = "Xu", coa: int | None = 60000) -> UUID:
        i = CatalogInstitution(
            new_id(),
            name.lower(),
            name,
            "US",
            None,
            "published",
            {"acceptance_rate": FactView({"min": 40, "max": 50}, "http://s", 2025)},
            coa_total=Decimal(coa) if coa else None,
            coa_currency="USD",
        )
        self.store.institutions[i.id] = i
        return i.id

    async def student(self) -> AdmissionContext:
        return await self.resolver.execute(Actor(STUDENT, frozenset({Role.STUDENT})))

    async def staff(self) -> AdmissionContext:
        return await self.resolver.execute(Actor(STAFF, frozenset({Role.COUNSELOR})))


async def test_catalog_search_pages_and_filters() -> None:
    w = World()
    for n in ("A", "B", "C"):
        w.inst(n)
    page = await w.catalog.search(CatalogFilters(country="us"), limit=2)
    assert [i.name for i in page.items] == ["A", "B"] and page.next_cursor == 2
    last = await w.catalog.search(CatalogFilters(), cursor=2, limit=2)
    assert [i.name for i in last.items] == ["C"] and last.next_cursor is None


async def test_add_is_idempotent_and_computes_affordability() -> None:
    w = World()
    ctx = await w.student()
    iid = w.inst()
    a = await w.lists.add(ctx, iid)
    b = await w.lists.add(ctx, iid)
    assert a.entry.id == b.entry.id and len(w.store.list_entries) == 1
    assert a.entry.affordability_status == "gap"
    assert a.affordability and a.affordability.gap == Decimal(45000)


async def test_remove_clears_the_deck_decision() -> None:
    w = World()
    ctx = await w.student()
    iid = w.inst()
    item = await w.lists.add(ctx, iid)
    w.store.decisions[(STUDENT, iid)] = "interested"
    await w.lists.remove(ctx, item.entry.id)
    assert not w.store.list_entries and not w.store.decisions


async def test_staff_cannot_edit_and_conflicts_detected() -> None:
    w = World()
    ctx = await w.student()
    item = await w.lists.add(ctx, w.inst())
    with pytest.raises(AdmissionNotFoundError):
        await w.lists.add(await w.staff(), w.inst("Z"))
    upd = await w.lists.update(
        ctx, item.entry.id, lock_version=item.entry.lock_version, bucket="reach"
    )
    assert upd.entry.bucket == "reach"
    with pytest.raises(AdmissionConflictError):
        await w.lists.update(
            ctx, item.entry.id, lock_version=item.entry.lock_version, notes="x"
        )


async def test_binding_round_needs_sign_off() -> None:
    w = World()
    ctx = await w.student()
    item = await w.lists.add(ctx, w.inst())
    lock = item.entry.lock_version
    with pytest.raises(AffordabilityGateError):
        await w.lists.update(ctx, item.entry.id, lock_version=lock, round_="ED")
    with pytest.raises(AdmissionForbiddenError):
        await w.lists.sign_off(ctx, item.entry.id, note=None)
    staff = await w.staff()
    check = await w.lists.sign_off(staff, item.entry.id, note="family agrees")
    assert check.signed_off_by == STAFF
    assert any(d.user_id == STUDENT for d in w.store.notifications)
    assert any(e.action == "list.affordability_sign_off" for e in w.store.audit)
    cur = w.store.list_entries[item.entry.id]
    ok = await w.lists.update(
        ctx, item.entry.id, lock_version=cur.lock_version, round_="ED"
    )
    assert ok.entry.round == "ED"


async def test_estimate_range_hidden_from_student_until_enabled() -> None:
    w = World()
    ctx = await w.student()
    item = await w.lists.add(ctx, w.inst())
    assert item.estimate.low is None and not item.estimate.range_visible
    assert item.estimate.label in {"reach", "target", "safety"}
    assert item.estimate.sources == ("http://s",) and item.estimate.verified
    staff_view = await w.lists.estimate(await w.staff(), item.entry.id)
    assert staff_view.low is not None and not staff_view.calibrated
    w.store.runtime[ESTIMATES_STUDENT_VISIBLE] = True
    again = await w.lists.estimate(ctx, item.entry.id)
    assert again.low is not None


async def test_label_override_wins_and_is_audited() -> None:
    w = World()
    ctx = await w.student()
    item = await w.lists.add(ctx, w.inst())
    with pytest.raises(AdmissionForbiddenError):
        await w.lists.override_label(
            ctx, item.entry.id, label="safety", note=None, lock_version=0
        )
    cur = w.store.list_entries[item.entry.id]
    await w.lists.override_label(
        await w.staff(),
        item.entry.id,
        label="reach",
        note="why",
        lock_version=cur.lock_version,
    )
    view = await w.lists.estimate(ctx, item.entry.id)
    assert view.label == "reach" and view.label_overridden
    assert any(e.action == "list.label_override" for e in w.store.audit)


async def test_sign_off_notifies_student_with_granted_event() -> None:
    from app.shared.notifications import NotificationType

    w = World()
    item = await w.lists.add(await w.student(), w.inst())
    await w.lists.sign_off(await w.staff(), item.entry.id, note=None)
    [n] = w.store.notifications
    assert n.user_id == STUDENT
    assert n.type == NotificationType.ADMISSION_AFFORDABILITY_SIGNOFF
    assert n.payload["event"] == "granted" and n.payload["path"] == "/list/"


async def test_sign_off_request_reaches_only_permitted_counselors() -> None:
    from app.shared.notifications import NotificationType

    w = World()
    item = await w.lists.add(await w.student(), w.inst())
    await w.lists.request_sign_off(await w.student(), item.entry.id)
    sent = [
        n.user_id
        for n in w.store.notifications
        if n.type == NotificationType.ADMISSION_AFFORDABILITY_SIGNOFF
    ]
    # The unassigned counselor never hears about this student.
    assert sent == [STAFF]


async def test_sign_off_request_skips_staff_after_consent_withdrawn() -> None:
    w = World()
    item = await w.lists.add(await w.student(), w.inst())
    w.consents.grants[STUDENT] = frozenset()
    w.store.notifications.clear()
    await w.lists.request_sign_off(await w.student(), item.entry.id)
    assert w.store.notifications == []

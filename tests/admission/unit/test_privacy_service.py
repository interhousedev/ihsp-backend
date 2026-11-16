"""Purpose consents, export, erasure and the student's audit view."""

from app.modules.admission.application.privacy import PrivacyService
from app.modules.admission.domain.errors import AdmissionNotFoundError
from app.modules.admission.domain.staff import AuditRecord
from app.modules.admission.ports.consent import (
    AI,
    PURPOSES,
    SHARING,
    STAFF_VIEW,
    MemoryPurposeConsents,
)
from app.shared.actor import Role
from tests.admission.unit.fakes import NOW, FakeUow
from tests.admission.unit.test_access_policy import STUDENT, World
from tests.fakes.clock import FixedClock

import pytest


def _svc(w: World) -> PrivacyService:
    return PrivacyService(
        lambda: FakeUow(w.store), MemoryPurposeConsents(), FixedClock(NOW)
    )


async def test_grant_and_withdraw_with_non_ai_mode() -> None:
    w = World()
    svc = _svc(w)
    ctx = await w.ctx(STUDENT, Role.STUDENT)
    assert (await svc.consent(ctx)).non_ai_mode
    state = await svc.grant(ctx, [AI, STAFF_VIEW])
    assert not state.non_ai_mode
    assert {g.purpose for g in state.grants if g.active} == {AI, STAFF_VIEW}
    state = await svc.withdraw(ctx, AI)
    assert state.non_ai_mode
    assert [e.action for e in w.store.audit] == [
        "consent.granted",
        "consent.granted",
        "consent.withdrawn",
    ]


async def test_withdrawing_staff_view_revokes_sharing() -> None:
    w = World()
    svc = _svc(w)
    ctx = await w.ctx(STUDENT, Role.STUDENT)
    await svc.grant(ctx, [STAFF_VIEW, SHARING])
    await svc.withdraw(ctx, SHARING)
    assert w.store.sharing_revoked == [STUDENT]
    await svc.withdraw(ctx, AI)
    assert w.store.sharing_revoked == [STUDENT]


async def test_unknown_purpose_is_404() -> None:
    w = World()
    svc = _svc(w)
    ctx = await w.ctx(STUDENT, Role.STUDENT)
    with pytest.raises(AdmissionNotFoundError):
        await svc.grant(ctx, ["nope"])
    with pytest.raises(AdmissionNotFoundError):
        await svc.withdraw(ctx, "nope")


async def test_export_erase_and_audit_use_the_caller_only() -> None:
    w = World()
    svc = _svc(w)
    ctx = await w.ctx(STUDENT, Role.STUDENT)
    w.store.export_tables = {"profiles": [{"student_id": "x"}]}
    w.store.audit_records = [
        AuditRecord(NOW, "user", "student.viewed", None, None, None)
    ]
    out = await svc.export(ctx)
    assert out["tables"] == w.store.export_tables and len(out["access_log"]) == 1
    await svc.grant(ctx, list(PURPOSES))
    assert await svc.erase(ctx) == {"profiles": 1}
    assert w.store.erased == [STUDENT]
    state = await svc.consent(ctx)
    assert not any(g.active for g in state.grants)
    assert [a.action for a in await svc.audit(ctx)] == ["student.viewed"]

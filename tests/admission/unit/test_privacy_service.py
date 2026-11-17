"""Purpose consents, export, erasure and the student's audit view."""

from uuid import UUID, uuid4

from app.modules.admission.application.privacy import PrivacyService
from app.modules.admission.domain.errors import AdmissionNotFoundError
from app.modules.admission.domain.staff import AuditRecord
from app.modules.admission.ports.consent import (
    AI,
    PURPOSE_VERSIONS,
    PURPOSES,
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


async def test_erase_forgets_the_search_index() -> None:
    from tests.fakes.admission_student_search import FakeStudentSearch

    w = World()
    search = FakeStudentSearch()
    svc = PrivacyService(
        lambda: FakeUow(w.store), MemoryPurposeConsents(), FixedClock(NOW), search
    )
    ctx = await w.ctx(STUDENT, Role.STUDENT)
    search.hits[STUDENT] = []
    await svc.erase(ctx)
    assert STUDENT not in search.hits


async def test_erase_deletes_files_runs_erasers_and_forgets_consents() -> None:
    w = World()
    consents = MemoryPurposeConsents()
    ctx = await w.ctx(STUDENT, Role.STUDENT)
    removed_files: list[UUID] = []
    seen: list[str] = []
    file_a, file_b = uuid4(), uuid4()
    w.store.stored_file_ids = [file_a, file_b]

    async def delete_file(file_id: UUID) -> None:
        removed_files.append(file_id)

    async def notifications(user_id: UUID) -> None:
        seen.append(f"notify:{user_id}")

    async def acceptances(user_id: UUID) -> None:
        seen.append(f"legal:{user_id}")

    svc = PrivacyService(
        lambda: FakeUow(w.store),
        consents,
        FixedClock(NOW),
        erasers=[notifications],
        file_remover=delete_file,
        final_erasers=[acceptances],
    )
    await svc.grant(ctx, list(PURPOSES))
    await svc.erase(ctx)
    assert removed_files == [file_a, file_b]
    assert seen == [f"notify:{STUDENT}", f"legal:{STUDENT}"]
    assert await consents.grants_of(STUDENT) == []


async def test_erase_withdraws_ai_consent_first() -> None:
    w = World()
    consents = MemoryPurposeConsents()
    ctx = await w.ctx(STUDENT, Role.STUDENT)
    seen: list[bool] = []

    async def probe(user_id: UUID) -> None:
        seen.append(AI in (await consents.granted([user_id])).get(user_id, set()))

    svc = PrivacyService(
        lambda: FakeUow(w.store), consents, FixedClock(NOW), erasers=[probe]
    )
    await svc.grant(ctx, [AI, STAFF_VIEW])
    await svc.erase(ctx)
    assert seen == [False]


async def test_bumped_purpose_version_needs_a_new_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = World()
    consents = MemoryPurposeConsents()
    svc = PrivacyService(lambda: FakeUow(w.store), consents, FixedClock(NOW))
    ctx = await w.ctx(STUDENT, Role.STUDENT)
    await svc.grant(ctx, [AI])
    assert AI in (await consents.granted([STUDENT]))[STUDENT]
    monkeypatch.setitem(PURPOSE_VERSIONS, AI, PURPOSE_VERSIONS[AI] + 1)
    assert STUDENT not in await consents.granted([STUDENT])
    state = await svc.consent(ctx)
    assert state.non_ai_mode
    assert state.pending == [AI]
    state = await svc.grant(ctx, [AI])
    assert not state.non_ai_mode
    assert state.pending == []
    assert [g.version for g in state.grants] == [PURPOSE_VERSIONS[AI]]
    assert AI in (await consents.granted([STUDENT]))[STUDENT]

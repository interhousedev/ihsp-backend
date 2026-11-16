"""Transcript officers: scoped by default, all students only by an admin's grant."""

import dataclasses

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.staff import StaffService
from app.modules.admission.domain.documents import Transcript
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.staff import StaffUser
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.admission.unit.fakes import FakeDirectory
from tests.admission.unit.fakes_documents import DocKit
from tests.admission.unit.test_access_policy import _assign, _role
from tests.admission.unit.test_staff_service import _service

import pytest

ADMIN = new_id()


async def _officer(k: DocKit, scope: str, ref: object = None) -> AdmissionContext:
    a = _assign("transcript_officer", scope, ref)  # type: ignore[arg-type]
    a = dataclasses.replace(a, user_id=k.officer)
    k.w.store.assignments[k.officer] = (a,)
    return await k.w.ctx(k.officer, Role.TRANSCRIPT_OFFICER)


async def _two_requests(k: DocKit) -> tuple[Transcript, Transcript]:
    mine, _ = await k.transcripts.request(await k.w.ctx(k.student, Role.STUDENT), "A")
    theirs, _ = await k.transcripts.request(await k.w.ctx(k.other, Role.STUDENT), "B")
    return mine, theirs


async def test_covering_officer_sees_and_acts_on_any_student() -> None:
    k = DocKit()
    mine, theirs = await _two_requests(k)
    officer = await _officer(k, "all")
    queue = await k.transcripts.officer_queue(officer)
    assert {r.request.id for r in queue} == {mine.id, theirs.id}
    await k.transcripts.set_pickup(officer, {"en": "Room 1"})
    await k.transcripts.done(officer, theirs.id, lock_version=theirs.lock_version)
    ready = await k.transcripts.officer_queue(officer, "ready")
    assert [r.request.id for r in ready] == [theirs.id]


async def test_scoped_officer_is_limited_to_assigned_students() -> None:
    k = DocKit()
    mine, theirs = await _two_requests(k)
    officer = await _officer(k, "student", k.student)
    queue = await k.transcripts.officer_queue(officer)
    assert [r.request.id for r in queue] == [mine.id]
    await k.transcripts.set_pickup(officer, {"en": "Room 1"})
    with pytest.raises(AdmissionNotFoundError):
        await k.transcripts.done(officer, theirs.id, lock_version=theirs.lock_version)
    await k.transcripts.done(officer, mine.id, lock_version=mine.lock_version)


def _admin_service(k: DocKit) -> StaffService:
    role = _role("transcript_officer")
    k.w.store.roles[role.id] = role
    directory = FakeDirectory(
        [StaffUser(k.officer, frozenset({"transcript_officer"}), True)]
    )
    return _service(k.w, directory)


async def test_admin_grants_covers_all_and_audits() -> None:
    k = DocKit()
    mine, theirs = await _two_requests(k)
    svc = _admin_service(k)
    admin = await k.w.ctx(ADMIN, Role.ADMIN)
    k.w.store.audit.clear()
    created = await svc.cover_all(admin, k.officer, None)
    assert created.scope_kind == "all" and created.granted_by == ADMIN
    [event] = k.w.store.audit
    assert event.action == "officer.covers_all_granted"
    assert event.actor_id == ADMIN and event.meta == {"user_id": str(k.officer)}
    listed = await svc.covering_officers(admin)
    assert [a.id for a, _ in listed] == [created.id]
    # The stored grant resolves to access over every student.
    k.w.store.assignments[k.officer] = (created,)
    officer = await k.w.ctx(k.officer, Role.TRANSCRIPT_OFFICER)
    queue = await k.transcripts.officer_queue(officer)
    assert {r.request.id for r in queue} == {mine.id, theirs.id}


async def test_admin_revoke_ends_coverage_and_audits() -> None:
    k = DocKit()
    svc = _admin_service(k)
    admin = await k.w.ctx(ADMIN, Role.ADMIN)
    created = await svc.cover_all(admin, k.officer, None)
    k.w.store.audit.clear()
    await svc.uncover_all(admin, created.id)
    assert [e.action for e in k.w.store.audit] == ["officer.covers_all_revoked"]
    assert await svc.covering_officers(admin) == []
    with pytest.raises(AdmissionNotFoundError):
        await svc.uncover_all(admin, created.id)


@pytest.mark.parametrize(
    "role", [Role.COUNSELOR, Role.TRANSCRIPT_OFFICER, Role.STUDENT, Role.TEACHER]
)
async def test_non_admin_cannot_grant_list_or_revoke(role: Role) -> None:
    k = DocKit()
    svc = _admin_service(k)
    admin = await k.w.ctx(ADMIN, Role.ADMIN)
    created = await svc.cover_all(admin, k.officer, None)
    ctx = await k.w.ctx(new_id(), role)
    with pytest.raises(AdmissionForbiddenError):
        await svc.cover_all(ctx, k.officer, None)
    with pytest.raises(AdmissionForbiddenError):
        await svc.uncover_all(ctx, created.id)
    with pytest.raises(AdmissionForbiddenError):
        await svc.covering_officers(ctx)
    with pytest.raises(AdmissionForbiddenError):
        await svc.officer_candidates(ctx, "")
    assert len(await svc.covering_officers(admin)) == 1


async def test_grant_requires_an_active_transcript_officer() -> None:
    k = DocKit()
    svc = _admin_service(k)
    admin = await k.w.ctx(ADMIN, Role.ADMIN)
    from app.modules.admission.domain.errors import DelegationDeniedError

    with pytest.raises(DelegationDeniedError):
        await svc.cover_all(admin, new_id(), None)
    svc._directory = FakeDirectory(
        [StaffUser(k.officer, frozenset({"counselor"}), True)]
    )
    with pytest.raises(DelegationDeniedError):
        await svc.cover_all(admin, k.officer, None)

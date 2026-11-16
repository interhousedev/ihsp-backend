"""Documents: versions, attach/detach, review, download guards."""

import dataclasses

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.documents import DocumentVersionRecord
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    ScanPendingError,
)
from app.modules.admission.domain.workflow import ListEntry
from app.shared.actor import Role
from app.shared.ids import new_id
from app.shared.notifications import NotificationType
from tests.admission.unit.fakes_documents import DocKit
from tests.admission.unit.test_access_policy import _assign

import pytest


async def _staff(k: DocKit, role: str = "counselor_full") -> AdmissionContext:
    a = _assign(role, "all", None)
    k.w.store.assignments[k.staff] = (dataclasses.replace(a, user_id=k.staff),)
    return await k.w.ctx(k.staff, Role.COUNSELOR)


def _entry(k: DocKit) -> ListEntry:
    e = ListEntry(new_id(), k.student, new_id())
    k.w.store.list_entries[e.id] = e
    return e


async def test_upload_then_new_version_supersedes_attachments() -> None:
    k = DocKit()
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    view = await k.docs.upload(ctx, "passport", "p.pdf", b"a")
    doc_id = view.doc.id
    entry = _entry(k)
    att = await k.docs.attach(ctx, doc_id, entry.id)
    assert att.document_version == 1 and att.status == "attached"
    v2 = await k.docs.new_version(ctx, doc_id, "p2.pdf", b"b")
    assert v2.doc.current_version == 2
    assert [a.status for a in k.d.attachments] == ["superseded"]
    assert len(k.files.stored) == 2


async def test_reattach_moves_to_current_version_and_detach() -> None:
    k = DocKit()
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    doc_id = (await k.docs.upload(ctx, "other", "x.pdf", b"a")).doc.id
    entry = _entry(k)
    await k.docs.attach(ctx, doc_id, entry.id)
    await k.docs.new_version(ctx, doc_id, "y.pdf", b"b")
    row = await k.docs.attach(ctx, doc_id, entry.id)
    assert row.document_version == 2 and row.status == "attached"
    await k.docs.detach(ctx, doc_id, entry.id)
    with pytest.raises(AdmissionNotFoundError):
        await k.docs.detach(ctx, doc_id, entry.id)


async def test_attach_to_foreign_entry_not_found() -> None:
    k = DocKit()
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    doc_id = (await k.docs.upload(ctx, "other", "x.pdf", b"a")).doc.id
    foreign = ListEntry(new_id(), k.other, new_id())
    k.w.store.list_entries[foreign.id] = foreign
    with pytest.raises(AdmissionNotFoundError):
        await k.docs.attach(ctx, doc_id, foreign.id)


async def test_student_upload_notifies_staff_and_review_reject_notifies_student() -> (
    None
):
    k = DocKit()
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    doc_id = (await k.docs.upload(ctx, "other", "x.pdf", b"a")).doc.id
    [n] = k.d.notifications
    assert n.type == NotificationType.ADMISSION_DOCUMENT_UPLOADED
    assert n.user_id == k.staff
    k.d.notifications.clear()
    staff = await _staff(k)
    view = await k.docs.review(staff, doc_id, accept=False, reason_code="blurry")
    assert view.doc.review_status == "rejected"
    [r] = k.d.notifications
    assert r.type == NotificationType.DOCUMENT_REJECTED and r.user_id == k.student


async def test_student_cannot_review() -> None:
    k = DocKit()
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    doc_id = (await k.docs.upload(ctx, "other", "x.pdf", b"a")).doc.id
    with pytest.raises(AdmissionForbiddenError):
        await k.docs.review(ctx, doc_id, accept=True)


async def test_download_signed_url_capped_and_scan_guard() -> None:
    k = DocKit()
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    doc_id = (await k.docs.upload(ctx, "passport", "p.pdf", b"a")).doc.id
    link = await k.docs.download(ctx, doc_id)
    assert link.url and k.files.ttls == [300]
    k.d.versions[0] = dataclasses.replace(k.d.versions[0], scan_status="infected")
    with pytest.raises(ScanPendingError):
        await k.docs.download(ctx, doc_id)


async def test_other_student_cannot_download() -> None:
    k = DocKit()
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    doc_id = (await k.docs.upload(ctx, "passport", "p.pdf", b"a")).doc.id
    other = await k.w.ctx(k.other, Role.STUDENT)
    with pytest.raises((AdmissionForbiddenError, AdmissionNotFoundError)):
        await k.docs.download(other, doc_id)


def test_version_record_is_frozen() -> None:
    v = DocumentVersionRecord(new_id(), 1, new_id(), "unscanned", new_id())
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.version = 2  # type: ignore[misc]

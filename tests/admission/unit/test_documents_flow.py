"""Documents: versions, attach/detach, review, download guards."""

import dataclasses

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.documents import DocumentVersionRecord
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    InvalidProofUrlError,
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
    await _staff(k)
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    doc_id = (await k.docs.upload(ctx, "other", "x.pdf", b"a")).doc.id
    [n] = k.d.notifications
    assert n.type == NotificationType.ADMISSION_DOCUMENT_UPLOADED
    assert n.user_id == k.staff
    assert n.payload["student_name"] == "Valiev Ali"
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


async def test_upload_notifies_only_staff_in_scope() -> None:
    k = DocKit()
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    await k.docs.upload(ctx, "other", "x.pdf", b"a")
    assert k.d.notifications == []


async def test_owner_cannot_replace_or_attach_institution_confidential_doc() -> None:
    k = DocKit()
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    doc_id = (await k.docs.upload(ctx, "other", "x.pdf", b"a")).doc.id
    doc = k.d.docs[doc_id]
    doc.uploaded_by = k.staff
    doc.owner_kind = "institution"
    doc.visibility = "confidential"
    entry = _entry(k)
    with pytest.raises(AdmissionNotFoundError):
        await k.docs.new_version(ctx, doc_id, "evil.pdf", b"b")
    with pytest.raises(AdmissionNotFoundError):
        await k.docs.attach(ctx, doc_id, entry.id)
    with pytest.raises(AdmissionNotFoundError):
        await k.docs.detach(ctx, doc_id, entry.id)


async def test_owner_cannot_add_version_to_institution_document() -> None:
    k = DocKit()
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    doc_id = (await k.docs.upload(ctx, "other", "x.pdf", b"a")).doc.id
    k.d.docs[doc_id].uploaded_by = k.staff
    k.d.docs[doc_id].visibility = "standard"
    with pytest.raises(AdmissionNotFoundError):
        await k.docs.new_version(ctx, doc_id, "evil.pdf", b"b")


async def test_owner_patches_only_student_checklist_items() -> None:
    from app.modules.admission.domain.documents import ChecklistItem

    k = DocKit()
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    mine = ChecklistItem(new_id(), k.student, "shared.passport", "passport")
    theirs = ChecklistItem(
        new_id(), k.student, "shared.transcript", "transcript", owner="officer"
    )
    k.d.items[mine.id] = mine
    k.d.items[theirs.id] = theirs
    done, _ = await k.docs.patch_checklist(ctx, mine.id, status="done")
    assert done.status == "done"
    with pytest.raises(AdmissionForbiddenError):
        await k.docs.patch_checklist(ctx, theirs.id, status="done")


async def test_checklist_names_the_university_of_per_entry_items() -> None:
    from app.modules.admission.domain.documents import ChecklistItem

    k = DocKit()
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    entry = _entry(k)
    k.d.institution_names[entry.institution_id] = "Columbia"
    shared = ChecklistItem(new_id(), k.student, "shared.passport", "passport")
    per_uni = ChecklistItem(
        new_id(), k.student, "entry.essay", "essay", list_entry_id=entry.id
    )
    k.d.items[shared.id] = shared
    k.d.items[per_uni.id] = per_uni
    names = {i.id: name for i, name in await k.docs.checklist(ctx)}
    assert names == {shared.id: None, per_uni.id: "Columbia"}


async def test_student_sets_importance_but_not_the_staff_link() -> None:
    from app.modules.admission.domain.documents import ChecklistItem

    k = DocKit()
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    item = ChecklistItem(
        new_id(), k.student, "shared.transcript", "transcript", owner="officer"
    )
    k.d.items[item.id] = item
    got, _ = await k.docs.patch_checklist(
        ctx, item.id, important=True, urgent_override=True
    )
    assert got.important and got.urgent_override is True
    got, _ = await k.docs.patch_checklist(ctx, item.id, urgent_override=None)
    assert got.important and got.urgent_override is None
    with pytest.raises(AdmissionForbiddenError):
        await k.docs.patch_checklist(ctx, item.id, source_url="https://x.uz")


async def test_staff_sets_and_clears_the_external_link() -> None:
    from app.modules.admission.domain.documents import ChecklistItem

    k = DocKit()
    staff = await _staff(k)
    item = ChecklistItem(new_id(), k.student, "shared.passport", "passport")
    k.d.items[item.id] = item
    got, _ = await k.docs.patch_checklist(staff, item.id, source_url="https://x.uz/p")
    assert got.source_url == "https://x.uz/p"
    got, _ = await k.docs.patch_checklist(staff, item.id, source_url="")
    assert got.source_url is None
    with pytest.raises(AdmissionForbiddenError):
        await k.docs.patch_checklist(staff, item.id, important=True)
    with pytest.raises(AdmissionForbiddenError):
        await k.docs.patch_checklist(staff, item.id, urgent_override=True)
    with pytest.raises(InvalidProofUrlError):
        await k.docs.patch_checklist(staff, item.id, source_url="http://x.uz")
    assert got.source_url is None

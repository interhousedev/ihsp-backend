"""Documents, versions, attachments, review, signed downloads, checklist (§6)."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.documents import (
    REJECT_NOTE_LIMIT,
    SIGNED_URL_MAX_SECONDS,
    AttachmentRecord,
    ChecklistItem,
    ChecklistStatus,
    DocumentRecord,
    DocumentVersionRecord,
)
from app.modules.admission.domain.errors import (
    AdmissionNotFoundError,
    CharLimitError,
    ScanPendingError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.workflow import DocumentKind, default_visibility
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork, UowFactory
from app.shared.actor import Role
from app.shared.clock import Clock
from app.shared.contracts.files import (
    FilePurpose,
    FilesApi,
    FileScope,
    SignedDownload,
)
from app.shared.contracts.identity import IdentityDirectory
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType

_BLOCKED_SCANS = frozenset({"infected", "failed", "pending_scan"})
_STAFF_NOTICE_ROLES = [Role.COUNSELOR]


@dataclass(frozen=True, slots=True)
class DocumentView:
    """A document with versions and attachments; `can_download` is per caller."""

    doc: DocumentRecord
    versions: list[DocumentVersionRecord]
    attachments: list[AttachmentRecord]
    can_download: bool


class DocumentService:
    """Upload, review, attach and download documents."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        clock: Clock,
        files: FilesApi | None,
        identity: IdentityDirectory | None,
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._access = access
        self._clock = clock
        self._files = files
        self._identity = identity

    # -- helpers ---------------------------------------------------------

    def _need_files(self) -> FilesApi:
        if self._files is None:
            raise AdmissionNotFoundError()
        return self._files

    async def _load(self, uow: AdmissionUnitOfWork, doc_id: UUID) -> DocumentRecord:
        doc = await uow.documents.get(doc_id)
        if doc is None:
            raise AdmissionNotFoundError()
        return doc

    async def _can_see_file(
        self, ctx: AdmissionContext, doc: DocumentRecord, perm: Permission
    ) -> bool:
        """Return True if the caller may read the file bytes of the document."""
        res = await self._access.require(
            ctx,
            doc.student_id,
            Permission.DOCUMENTS_READ,
            object_type="document",
            object_id=doc.id,
        )
        if doc.visibility != "confidential":
            return True
        if res.owner:
            return doc.uploaded_by == ctx.user_id
        return perm in res.permissions

    async def _view(
        self,
        ctx: AdmissionContext,
        uow: AdmissionUnitOfWork,
        docs: list[DocumentRecord],
    ) -> list[DocumentView]:
        ids = [d.id for d in docs]
        attachments = await uow.documents.attachments(ids) if ids else []
        out = []
        for doc in docs:
            res = await self._access.resolve(ctx, doc.student_id)
            can = doc.visibility != "confidential" or (
                (res.owner and doc.uploaded_by == ctx.user_id)
                or Permission.CONFIDENTIAL_READ in res.permissions
            )
            out.append(
                DocumentView(
                    doc,
                    await uow.documents.versions(doc.id),
                    [a for a in attachments if a.document_id == doc.id],
                    can,
                )
            )
        return out

    async def _staff_ids(self) -> list[UUID]:
        if self._identity is None:
            return []
        return await self._identity.user_ids_with_roles(_STAFF_NOTICE_ROLES)

    async def _store(
        self,
        doc: DocumentRecord,
        student_id: UUID,
        name: str,
        data: bytes,
        uploader: UUID,
    ) -> DocumentVersionRecord:
        file = await self._need_files().store_bytes(
            owner_id=student_id,
            scope=FileScope.STUDENT,
            purpose=FilePurpose.ADMISSION_DOCUMENT,
            name=name,
            data=data,
            confidential=doc.visibility == "confidential",
        )
        return DocumentVersionRecord(
            document_id=doc.id,
            version=doc.current_version + 1,
            file_id=file.id,
            scan_status="unscanned",
            uploaded_by=uploader,
        )

    # -- documents -------------------------------------------------------

    async def listing(
        self, ctx: AdmissionContext, student_id: UUID | None = None
    ) -> list[DocumentView]:
        """List one student's documents (the caller's own by default)."""
        target = student_id or ctx.user_id
        await self._access.require(ctx, target, Permission.DOCUMENTS_READ)
        async with self._uow() as uow:
            docs = await uow.documents.for_students([target])
            return await self._view(ctx, uow, docs)

    async def upload(
        self,
        ctx: AdmissionContext,
        kind: DocumentKind,
        name: str,
        data: bytes,
        *,
        student_id: UUID | None = None,
    ) -> DocumentView:
        """Create a document with its first version."""
        target = student_id or ctx.user_id
        res = await self._access.require(
            ctx,
            target,
            (
                Permission.DOCUMENTS_READ
                if target == ctx.user_id
                else Permission.DOCUMENTS_ATTACH
            ),
        )
        async with self._uow() as uow:
            doc = DocumentRecord(
                id=new_id(),
                student_id=target,
                kind=kind,
                visibility=default_visibility(kind),
                uploaded_by=ctx.user_id,
                owner_kind="student" if res.owner else "institution",
            )
            version = await self._store(doc, target, name, data, ctx.user_id)
            doc.current_version = version.version
            await uow.documents.add(doc)
            await uow.documents.add_version(version)
            uow.access.audit(
                AuditEvent(
                    "document.uploaded",
                    ctx.user_id,
                    target,
                    object_type="document",
                    object_id=doc.id,
                )
            )
            await self._notify_uploaded(uow, doc, res.owner)
            await uow.commit()
            return (await self._view(ctx, uow, [doc]))[0]

    async def _notify_uploaded(
        self,
        uow: AdmissionUnitOfWork,
        doc: DocumentRecord,
        by_student: bool,
    ) -> None:
        if not by_student:
            return
        for user_id in await self._staff_ids():
            uow.notify(
                NotificationDraft(
                    user_id=user_id,
                    type=NotificationType.ADMISSION_DOCUMENT_UPLOADED,
                    payload={"student_name": "", "student_id": str(doc.student_id)},
                    dedupe_key=(
                        f"document:{doc.id}:uploaded:{doc.current_version}:{user_id}"
                    ),
                )
            )

    async def new_version(
        self, ctx: AdmissionContext, doc_id: UUID, name: str, data: bytes
    ) -> DocumentView:
        """Add a version; attachments of older versions need re-confirmation."""
        async with self._uow() as uow:
            doc = await self._load(uow, doc_id)
            res = await self._access.require(
                ctx,
                doc.student_id,
                (
                    Permission.DOCUMENTS_READ
                    if doc.student_id == ctx.user_id
                    else Permission.DOCUMENTS_ATTACH
                ),
                object_type="document",
                object_id=doc.id,
            )
            version = await self._store(doc, doc.student_id, name, data, ctx.user_id)
            lock = doc.lock_version
            doc.current_version = version.version
            doc.review_status = "none"
            doc.reject_reason_code = None
            doc.reject_note = None
            await uow.documents.add_version(version)
            await uow.documents.save(doc, expected_lock=lock)
            await uow.documents.supersede_attachments(doc.id, doc.current_version)
            await self._notify_uploaded(uow, doc, res.owner)
            await uow.commit()
            return (await self._view(ctx, uow, [doc]))[0]

    async def review(
        self,
        ctx: AdmissionContext,
        doc_id: UUID,
        *,
        accept: bool,
        reason_code: str | None = None,
        note: str | None = None,
    ) -> DocumentView:
        """Accept or reject; a rejection tells the student."""
        if note is not None and len(note) > REJECT_NOTE_LIMIT:
            raise CharLimitError(
                params={"field": "note", "limit": str(REJECT_NOTE_LIMIT)}
            )
        async with self._uow() as uow:
            doc = await self._load(uow, doc_id)
            await self._access.require(
                ctx,
                doc.student_id,
                Permission.DOCUMENTS_REVIEW,
                object_type="document",
                object_id=doc.id,
            )
            lock = doc.lock_version
            doc.review_status = "accepted" if accept else "rejected"
            doc.reject_reason_code = None if accept else reason_code
            doc.reject_note = None if accept else note
            doc.reviewed_by = ctx.user_id
            doc.reviewed_at = self._clock.now()
            await uow.documents.save(doc, expected_lock=lock)
            uow.access.audit(
                AuditEvent(
                    "document.reviewed",
                    ctx.user_id,
                    doc.student_id,
                    object_type="document",
                    object_id=doc.id,
                    meta={"status": doc.review_status},
                )
            )
            if not accept:
                uow.notify(
                    NotificationDraft(
                        user_id=doc.student_id,
                        type=NotificationType.DOCUMENT_REJECTED,
                        payload={"document_id": str(doc.id)},
                        dedupe_key=f"document:{doc.id}:rejected:{doc.lock_version}",
                    )
                )
            await uow.commit()
            return (await self._view(ctx, uow, [doc]))[0]

    async def attach(
        self, ctx: AdmissionContext, doc_id: UUID, list_entry_id: UUID
    ) -> AttachmentRecord:
        """Attach the current version to a list entry of the same student."""
        async with self._uow() as uow:
            doc = await self._load(uow, doc_id)
            await self._access.require(
                ctx,
                doc.student_id,
                (
                    Permission.DOCUMENTS_READ
                    if doc.student_id == ctx.user_id
                    else Permission.DOCUMENTS_ATTACH
                ),
                object_type="document",
                object_id=doc.id,
            )
            entry = await uow.shortlist.entry(list_entry_id)
            if entry is None or entry.student_id != doc.student_id:
                raise AdmissionNotFoundError()
            now = self._clock.now()
            row = await uow.documents.attachment(doc.id, list_entry_id)
            if row is None:
                row = await uow.documents.add_attachment(
                    AttachmentRecord(
                        id=new_id(),
                        document_id=doc.id,
                        document_version=doc.current_version,
                        list_entry_id=list_entry_id,
                        attached_by=ctx.user_id,
                        attached_at=now,
                    )
                )
            else:
                row.document_version = doc.current_version
                row.status = "attached"
                row.attached_by = ctx.user_id
                row.attached_at = now
                await uow.documents.save_attachment(row)
            if doc.student_id != ctx.user_id:
                uow.notify(
                    NotificationDraft(
                        user_id=doc.student_id,
                        type=NotificationType.DOCUMENT_ATTACHED,
                        payload={"count": "1"},
                        dedupe_key=(
                            f"document:{doc.id}:attached:{list_entry_id}:"
                            f"{doc.current_version}"
                        ),
                    )
                )
            await uow.commit()
            return row

    async def detach(
        self, ctx: AdmissionContext, doc_id: UUID, list_entry_id: UUID
    ) -> None:
        """Remove the attachment of a document from a list entry."""
        async with self._uow() as uow:
            doc = await self._load(uow, doc_id)
            await self._access.require(
                ctx,
                doc.student_id,
                (
                    Permission.DOCUMENTS_READ
                    if doc.student_id == ctx.user_id
                    else Permission.DOCUMENTS_ATTACH
                ),
                object_type="document",
                object_id=doc.id,
            )
            row = await uow.documents.attachment(doc.id, list_entry_id)
            if row is None:
                raise AdmissionNotFoundError()
            row.status = "detached"
            await uow.documents.save_attachment(row)
            await uow.commit()

    async def download(
        self, ctx: AdmissionContext, doc_id: UUID, version: int | None = None
    ) -> SignedDownload:
        """Return a signed link (at most 5 minutes) after every check again."""
        files = self._need_files()
        async with self._uow() as uow:
            doc = await self._load(uow, doc_id)
            if doc.visibility == "confidential" and doc.student_id != ctx.user_id:
                await self._access.require(
                    ctx,
                    doc.student_id,
                    Permission.CONFIDENTIAL_READ,
                    object_type="document",
                    object_id=doc.id,
                )
            if not await self._can_see_file(ctx, doc, Permission.CONFIDENTIAL_READ):
                raise AdmissionNotFoundError()
            row = await uow.documents.version(doc.id, version or doc.current_version)
            if row is None:
                raise AdmissionNotFoundError()
            if row.scan_status in _BLOCKED_SCANS:
                raise ScanPendingError()
            link = await files.issue_signed_download(
                row.file_id, ttl_seconds=SIGNED_URL_MAX_SECONDS
            )
            uow.access.audit(
                AuditEvent(
                    "document.downloaded",
                    ctx.user_id,
                    doc.student_id,
                    object_type="document",
                    object_id=doc.id,
                    meta={"version": str(row.version)},
                )
            )
            await uow.commit()
            return link

    async def staff_queue(
        self, ctx: AdmissionContext, review_status: str | None = None
    ) -> list[DocumentView]:
        """List documents of the students in the caller's scope."""
        scope = await self._access.students_in_scope(ctx)
        ids: Collection[UUID] | None = None if scope is None else list(scope)
        async with self._uow() as uow:
            docs = await uow.documents.for_students(ids, review_status=review_status)
            allowed = []
            for doc in docs:
                res = await self._access.resolve(ctx, doc.student_id)
                if Permission.DOCUMENTS_REVIEW in res.permissions:
                    allowed.append(doc)
            return await self._view(ctx, uow, allowed)

    # -- checklist -------------------------------------------------------

    async def checklist(
        self, ctx: AdmissionContext, student_id: UUID | None = None
    ) -> list[ChecklistItem]:
        """Return the checklist of the student."""
        target = student_id or ctx.user_id
        await self._access.require(ctx, target, Permission.DOCUMENTS_READ)
        async with self._uow() as uow:
            return await uow.checklist.for_student(target)

    async def patch_checklist(
        self,
        ctx: AdmissionContext,
        item_id: UUID,
        *,
        status: ChecklistStatus | None = None,
        document_id: UUID | None = None,
    ) -> ChecklistItem:
        """Change an item's status or link it to a document of the same student."""
        async with self._uow() as uow:
            item = await uow.checklist.get(item_id)
            if item is None:
                raise AdmissionNotFoundError()
            await self._access.require(
                ctx,
                item.student_id,
                (
                    Permission.DOCUMENTS_READ
                    if item.student_id == ctx.user_id
                    else Permission.DOCUMENTS_ATTACH
                ),
                object_type="checklist",
                object_id=item.id,
            )
            if document_id is not None:
                doc = await uow.documents.get(document_id)
                if doc is None or doc.student_id != item.student_id:
                    raise AdmissionNotFoundError()
                item.document_id = document_id
            lock = item.lock_version
            if status is not None:
                item.status = status
            saved = await uow.checklist.save(item, expected_lock=lock)
            await uow.commit()
            return saved

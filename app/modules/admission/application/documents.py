"""Documents, versions, attachments, review, signed downloads, checklist (§6)."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.staff import display_name
from app.modules.admission.application.staff_notice import permitted_staff
from app.modules.admission.domain.access import Resolution
from app.modules.admission.domain.checklist import UNSET, Unset, clean_source_url
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
    AdmissionForbiddenError,
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
from app.shared.limits import LimitsProvider
from app.shared.notifications import NotificationDraft, NotificationType

_BLOCKED_SCANS = frozenset({"infected", "failed", "pending_scan"})
_STAFF_NOTICE_ROLES = [Role.COUNSELOR]


def _check_patch_rights(
    res: Resolution,
    item: ChecklistItem,
    *,
    edits_status: bool,
    edits_link: bool,
    edits_priority: bool,
) -> None:
    if edits_status and res.owner and item.owner != "student":
        raise AdmissionForbiddenError(params={"permission": "checklist:edit"})
    if edits_link and res.owner:
        raise AdmissionForbiddenError(params={"permission": "checklist:link"})
    if edits_priority and not res.owner:
        raise AdmissionForbiddenError(params={"permission": "checklist:priority"})


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
        limits: LimitsProvider,
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._access = access
        self._clock = clock
        self._files = files
        self._identity = identity
        self._limits = limits

    async def upload_limit(self, user_id: UUID) -> int:
        """The largest upload accepted now, in bytes (admin-editable)."""
        return int((await self._limits.for_user(user_id)).admit_upload_max_bytes)

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

    async def _require_write(
        self, ctx: AdmissionContext, doc: DocumentRecord, *, own_only: bool = False
    ) -> Resolution:
        """Check write access; an owner touches only files they put there.

        Confidential documents and institution-uploaded ones are hidden from the
        owner (404); new versions are further limited to the owner's own uploads.
        """
        if doc.student_id != ctx.user_id:
            return await self._access.require(
                ctx,
                doc.student_id,
                Permission.DOCUMENTS_ATTACH,
                object_type="document",
                object_id=doc.id,
            )
        res = await self._access.require(
            ctx,
            doc.student_id,
            Permission.DOCUMENTS_READ,
            object_type="document",
            object_id=doc.id,
        )
        foreign = doc.uploaded_by != ctx.user_id
        if doc.visibility == "confidential" and foreign:
            raise AdmissionNotFoundError()
        if own_only and (foreign or doc.visibility == "confidential"):
            raise AdmissionNotFoundError()
        return res

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

    async def _scoped_staff(self, student_id: UUID) -> list[UUID]:
        """Return the counselors who may review this student's documents."""
        return await permitted_staff(
            self._identity,
            self._uow,
            self._access,
            _STAFF_NOTICE_ROLES,
            student_id,
            Permission.DOCUMENTS_REVIEW,
        )

    async def _student_name(self, student_id: UUID) -> str:
        if self._identity is None:
            return ""
        ref = (await self._identity.get_users([student_id])).get(student_id)
        return display_name(ref) if ref else ""

    async def _notify_uploaded(
        self,
        uow: AdmissionUnitOfWork,
        doc: DocumentRecord,
        by_student: bool,
    ) -> None:
        if not by_student:
            return
        name = await self._student_name(doc.student_id)
        for user_id in await self._scoped_staff(doc.student_id):
            uow.notify(
                NotificationDraft(
                    user_id=user_id,
                    type=NotificationType.ADMISSION_DOCUMENT_UPLOADED,
                    payload={"student_name": name, "student_id": str(doc.student_id)},
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
            res = await self._require_write(ctx, doc, own_only=True)
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
            await self._require_write(ctx, doc)
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
            await self._require_write(ctx, doc)
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
    ) -> list[tuple[ChecklistItem, str | None]]:
        """Return the student checklist; per-university items name the institution."""
        target = student_id or ctx.user_id
        await self._access.require(ctx, target, Permission.DOCUMENTS_READ)
        async with self._uow() as uow:
            items = await uow.checklist.for_student(target)
            entries = await uow.shortlist.entries(target)
            by_entry = {e.id: e.institution_id for e in entries}
            names = await uow.deadlines.institution_names(set(by_entry.values()))
        return [
            (
                i,
                (
                    names.get(by_entry[i.list_entry_id])
                    if i.list_entry_id in by_entry
                    else None
                ),
            )
            for i in items
        ]

    @staticmethod
    async def _attach_document(
        uow: AdmissionUnitOfWork, item: ChecklistItem, document_id: UUID
    ) -> None:
        doc = await uow.documents.get(document_id)
        if doc is None or doc.student_id != item.student_id:
            raise AdmissionNotFoundError()
        item.document_id = document_id

    async def patch_checklist(
        self,
        ctx: AdmissionContext,
        item_id: UUID,
        *,
        status: ChecklistStatus | None = None,
        document_id: UUID | None = None,
        important: bool | None = None,
        urgent_override: bool | None | Unset = UNSET,
        source_url: str | None | Unset = UNSET,
    ) -> tuple[ChecklistItem, str | None]:
        """Change an item; the university name is set for per-university items.

        Status and document follow the owner rule; importance and the urgency
        override are the student's own priority; the external link is staff-set.
        """
        async with self._uow() as uow:
            item = await uow.checklist.get(item_id)
            if item is None:
                raise AdmissionNotFoundError()
            res = await self._access.require(
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
            _check_patch_rights(
                res,
                item,
                edits_status=status is not None or document_id is not None,
                edits_link=not isinstance(source_url, Unset),
                edits_priority=important is not None
                or not isinstance(urgent_override, Unset),
            )
            if not isinstance(source_url, Unset):
                item.source_url = clean_source_url(source_url)
            if document_id is not None:
                await self._attach_document(uow, item, document_id)
            lock = item.lock_version
            if status is not None:
                item.status = status
            if important is not None:
                item.important = important
            if not isinstance(urgent_override, Unset):
                item.urgent_override = urgent_override
            saved = await uow.checklist.save(item, expected_lock=lock)
            entry = (
                await uow.shortlist.entries(saved.student_id)
                if saved.list_entry_id
                else []
            )
            inst_ids = {e.institution_id for e in entry if e.id == saved.list_entry_id}
            names = await uow.deadlines.institution_names(inst_ids) if inst_ids else {}
            await uow.commit()
            return saved, next(iter(names.values()), None)

"""Transcript requests, the officer's Done/Undo and the staff overview (§6.1)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.documents import DocumentView
from app.modules.admission.application.runtime_settings import RuntimeSettingsService
from app.modules.admission.application.staff_notice import permitted_staff
from app.modules.admission.domain.documents import (
    DESTINATION_NOTE_LIMIT,
    PICKUP_LIMIT,
    REMIND_COOLDOWN,
    DocumentRecord,
    DocumentVersionRecord,
    OfficerSettings,
    Transcript,
    pick_text,
)
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    CharLimitError,
    PickupNotSetError,
    UndoExpiredError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.workflow import TRANSCRIPT_UNDO_SECONDS
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork, UowFactory
from app.shared.actor import Role
from app.shared.clock import Clock
from app.shared.contracts.academic import AcademicMembership
from app.shared.contracts.files import FilePurpose, FilesApi, FileScope
from app.shared.contracts.identity import IdentityDirectory, UserRef
from app.shared.ids import new_id, uuid_to_b64
from app.shared.notifications import NotificationDraft, NotificationType

_OVERSEE_ROLES = (Role.COUNSELOR, Role.ADMIN)


@dataclass(frozen=True, slots=True)
class TranscriptView:
    """A request with the display fields the officer is allowed to see."""

    request: Transcript
    student_name: str
    class_name: str


@dataclass(frozen=True, slots=True)
class DoneResult:
    """The outcome of Done; `already` is True when it was ready before."""

    request: Transcript
    already: bool


def full_name(user: UserRef | None) -> str:
    """Return 'Last First' or an empty string."""
    return f"{user.last_name} {user.first_name}".strip() if user else ""


class TranscriptService:
    """Student requests, officer fulfilment and staff oversight."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        runtime: RuntimeSettingsService,
        clock: Clock,
        membership: AcademicMembership,
        files: FilesApi | None,
        identity: IdentityDirectory | None,
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._access = access
        self._runtime = runtime
        self._clock = clock
        self._membership = membership
        self._files = files
        self._identity = identity

    # -- helpers ---------------------------------------------------------

    async def _users(self, ids: Iterable[UUID]) -> dict[UUID, UserRef]:
        wanted = list(dict.fromkeys(ids))
        if self._identity is None or not wanted:
            return {}
        return await self._identity.get_users(wanted)

    async def _notice_to(
        self, roles: tuple[Role, ...], student_id: UUID, permission: Permission
    ) -> list[UUID]:
        return await permitted_staff(
            self._identity, self._uow, self._access, roles, student_id, permission
        )

    async def _view(self, items: list[Transcript]) -> list[TranscriptView]:
        users = await self._users(t.student_id for t in items)
        views = []
        for item in items:
            ref = await self._membership.student(item.student_id)
            views.append(
                TranscriptView(
                    item,
                    full_name(users.get(item.student_id)),
                    ref.group_name if ref else "",
                )
            )
        return views

    async def _load(self, uow: AdmissionUnitOfWork, request_id: UUID) -> Transcript:
        request = await uow.transcripts.get(request_id)
        if request is None:
            raise AdmissionNotFoundError()
        return request

    async def _owner_or(
        self, ctx: AdmissionContext, request: Transcript, perm: Permission
    ) -> bool:
        """Authorize: the owner, or staff holding `perm`; True when the owner."""
        res = await self._access.require(
            ctx,
            request.student_id,
            Permission.DOCUMENTS_READ if request.student_id == ctx.user_id else perm,
            object_type="transcript",
            object_id=request.id,
        )
        return res.owner

    # -- student ---------------------------------------------------------

    async def request(
        self, ctx: AdmissionContext, destination_note: str
    ) -> tuple[Transcript, bool]:
        """Open a request; an already open one is returned unchanged (created=False)."""
        note = destination_note.strip()
        if len(note) > DESTINATION_NOTE_LIMIT:
            raise CharLimitError(
                params={"field": "destination_note", "limit": DESTINATION_NOTE_LIMIT}
            )
        res = await self._access.require(ctx, ctx.user_id, Permission.DOCUMENTS_READ)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "transcripts:request"})
        officers = await self._notice_to(
            (Role.TRANSCRIPT_OFFICER,), ctx.user_id, Permission.TRANSCRIPTS_FULFIL
        )
        async with self._uow() as uow:
            existing = await uow.transcripts.open_of(ctx.user_id)
            if existing is not None:
                return existing, False
            request = await uow.transcripts.add(
                Transcript(id=new_id(), student_id=ctx.user_id, destination_note=note)
            )
            users = await self._users([ctx.user_id])
            ref = await self._membership.student(ctx.user_id)
            payload = {
                "student_name": full_name(users.get(ctx.user_id)),
                "class_name": ref.group_name if ref else "",
                "destination_note": note,
                "request_id_b64": uuid_to_b64(request.id),
            }
            for officer in officers:
                uow.notify(
                    NotificationDraft(
                        user_id=officer,
                        type=NotificationType.TRANSCRIPT_REQUESTED,
                        payload=payload,
                        dedupe_key=f"transcript:{request.id}:requested:{officer}",
                    )
                )
            if not officers:
                await self._unrouted(uow, request, payload["student_name"])
            uow.access.audit(
                AuditEvent(
                    "transcript.requested",
                    ctx.user_id,
                    ctx.user_id,
                    object_type="transcript",
                    object_id=request.id,
                )
            )
            await uow.commit()
        return request, True

    async def _unrouted(
        self, uow: AdmissionUnitOfWork, request: Transcript, name: str
    ) -> None:
        for user_id in await self._notice_to(
            _OVERSEE_ROLES, request.student_id, Permission.TRANSCRIPTS_OVERSEE
        ):
            uow.notify(
                NotificationDraft(
                    user_id=user_id,
                    type=NotificationType.TRANSCRIPT_UNROUTED,
                    payload={"student_name": name},
                    dedupe_key=f"transcript:{request.id}:unrouted:{user_id}",
                )
            )

    async def mine(self, ctx: AdmissionContext) -> list[Transcript]:
        """The student's own requests, newest first."""
        await self._access.require(ctx, ctx.user_id, Permission.DOCUMENTS_READ)
        async with self._uow() as uow:
            return await uow.transcripts.of_student(ctx.user_id)

    async def cancel(self, ctx: AdmissionContext, request_id: UUID) -> Transcript:
        """Cancel an open request (the student, or staff with `transcripts:oversee`)."""
        async with self._uow() as uow:
            request = await self._load(uow, request_id)
            await self._owner_or(ctx, request, Permission.TRANSCRIPTS_OVERSEE)
            if request.status == "cancelled":
                return request
            lock = request.lock_version
            request.move("cancelled")
            request.cancelled_by = ctx.user_id
            request.cancelled_at = self._clock.now()
            saved = await uow.transcripts.save(request, expected_lock=lock)
            uow.access.audit(
                AuditEvent(
                    "transcript.cancelled",
                    ctx.user_id,
                    request.student_id,
                    object_type="transcript",
                    object_id=request.id,
                )
            )
            await uow.commit()
        return saved

    # -- officer ---------------------------------------------------------

    async def officer_queue(
        self, ctx: AdmissionContext, status: str = "requested"
    ) -> list[TranscriptView]:
        """Requests of one status (open by default) with name, class and note only."""
        scope = await self._access.students_in_scope(ctx)
        async with self._uow() as uow:
            items = await uow.transcripts.listing(scope, status)
        allowed = await self._permitted(
            ctx, items, Permission.TRANSCRIPTS_FULFIL, "officer_queue"
        )
        return await self._view(allowed)

    async def _permitted(
        self,
        ctx: AdmissionContext,
        items: list[Transcript],
        permission: Permission,
        listing: str,
    ) -> list[Transcript]:
        """Keep the rows the caller may act on; one audit entry for the list."""
        allowed: list[Transcript] = []
        for item in items:
            res = await self._access.resolve(ctx, item.student_id)
            if res.in_scope and permission in res.permissions:
                allowed.append(item)
        if allowed and not all(i.student_id == ctx.user_id for i in allowed):
            async with self._uow() as uow:
                uow.access.audit(
                    AuditEvent(
                        action="transcript.listed",
                        actor_id=ctx.user_id,
                        student_id=None,
                        object_type="transcript",
                        meta={
                            "list": listing,
                            "permission": permission.value,
                            "count": len(allowed),
                        },
                    )
                )
                await uow.commit()
        return allowed

    async def pickup_for(self, ctx: AdmissionContext) -> dict[str, str] | None:
        """The pickup text of the officer, else the admin default."""
        async with self._uow() as uow:
            own = await uow.transcripts.officer_settings(ctx.user_id)
        if own and own.pickup_location:
            return own.pickup_location
        return (await self._runtime.get()).pickup_location()

    async def get_officer_settings(self, ctx: AdmissionContext) -> OfficerSettings:
        """The officer's own pickup texts."""
        self._need_officer(ctx)
        async with self._uow() as uow:
            return await uow.transcripts.officer_settings(
                ctx.user_id
            ) or OfficerSettings(ctx.user_id)

    def _need_officer(self, ctx: AdmissionContext) -> None:
        if not {Role.TRANSCRIPT_OFFICER, Role.ADMIN} & ctx.actor.roles:
            raise AdmissionForbiddenError(params={"permission": "transcripts:fulfil"})

    async def set_pickup(
        self, ctx: AdmissionContext, texts: dict[str, str]
    ) -> OfficerSettings:
        """Set the officer's pickup text per locale (plain text, trimmed)."""
        self._need_officer(ctx)
        clean = {
            k: " ".join(v.split())
            for k, v in texts.items()
            if k in ("uz", "ru", "en") and v.strip()
        }
        for value in clean.values():
            if len(value) > PICKUP_LIMIT:
                raise CharLimitError(
                    params={"field": "pickup_location", "limit": PICKUP_LIMIT}
                )
        async with self._uow() as uow:
            saved = await uow.transcripts.save_officer_settings(
                OfficerSettings(ctx.user_id, clean), None
            )
            uow.access.audit(AuditEvent("officer.pickup_changed", ctx.user_id, None))
            await uow.commit()
        return saved

    async def done(
        self,
        ctx: AdmissionContext,
        request_id: UUID,
        *,
        lock_version: int | None = None,
    ) -> DoneResult:
        """Mark ready: snapshot the pickup, open the undo window, queue the notice."""
        pickup = await self.pickup_for(ctx)
        async with self._uow() as uow:
            request = await self._load(uow, request_id)
            await self._access.require(
                ctx,
                request.student_id,
                Permission.TRANSCRIPTS_FULFIL,
                object_type="transcript",
                object_id=request.id,
            )
            if request.status == "ready":
                return DoneResult(request, True)
            if request.status != "requested":
                raise AdmissionConflictError()
            if lock_version is not None and lock_version != request.lock_version:
                raise AdmissionConflictError()
            if not pickup:
                raise PickupNotSetError()
            users = await self._users([request.student_id])
            student = users.get(request.student_id)
            snapshot = pick_text(pickup, student.locale if student else "ru") or ""
            now = self._clock.now()
            lock = request.lock_version
            request.move("ready")
            request.ready_at = now
            request.ready_by = ctx.user_id
            request.undo_until = now + dt.timedelta(seconds=TRANSCRIPT_UNDO_SECONDS)
            request.pickup_location_snapshot = snapshot
            saved = await uow.transcripts.save(request, expected_lock=lock)
            uow.notify(
                NotificationDraft(
                    user_id=saved.student_id,
                    type=NotificationType.TRANSCRIPT_READY,
                    payload={"pickup_location": snapshot},
                    dedupe_key=saved.ready_key(),
                    scheduled_at=saved.undo_until,
                )
            )
            uow.access.audit(
                AuditEvent(
                    "transcript.ready",
                    ctx.user_id,
                    saved.student_id,
                    object_type="transcript",
                    object_id=saved.id,
                )
            )
            await uow.commit()
        return DoneResult(saved, False)

    async def undo(self, ctx: AdmissionContext, request_id: UUID) -> Transcript:
        """Take Done back while the student's notice is still pending."""
        async with self._uow() as uow:
            request = await self._load(uow, request_id)
            await self._access.require(
                ctx,
                request.student_id,
                Permission.TRANSCRIPTS_FULFIL,
                object_type="transcript",
                object_id=request.id,
            )
            now = self._clock.now()
            if (
                request.status != "ready"
                or request.undo_until is None
                or request.undo_until <= now
            ):
                raise UndoExpiredError()
            if not await uow.cancel_notification(request.ready_key()):
                raise UndoExpiredError()
            lock = request.lock_version
            request.move("requested")
            request.ready_at = None
            request.ready_by = None
            request.undo_until = None
            request.pickup_location_snapshot = None
            saved = await uow.transcripts.save(request, expected_lock=lock)
            uow.access.audit(
                AuditEvent(
                    "transcript.undo",
                    ctx.user_id,
                    saved.student_id,
                    object_type="transcript",
                    object_id=saved.id,
                )
            )
            await uow.commit()
        return saved

    # -- staff -----------------------------------------------------------

    async def overview(
        self, ctx: AdmissionContext, status: str | None = None
    ) -> list[TranscriptView]:
        """Requests of the students in scope, for the staff queue."""
        scope = await self._access.students_in_scope(ctx)
        async with self._uow() as uow:
            items = await uow.transcripts.listing(scope, status)
        out = await self._permitted(
            ctx, items, Permission.TRANSCRIPTS_OVERSEE, "overview"
        )
        return await self._view(out)

    async def remind(self, ctx: AdmissionContext, request_id: UUID) -> Transcript:
        """Nudge the officers about an open request, at most once a day."""
        async with self._uow() as uow:
            request = await self._load(uow, request_id)
            await self._access.require(
                ctx,
                request.student_id,
                Permission.TRANSCRIPTS_OVERSEE,
                object_type="transcript",
                object_id=request.id,
            )
            now = self._clock.now()
            if request.status != "requested":
                raise AdmissionConflictError()
            last = request.last_reminded_at
            if last is not None and now - last < REMIND_COOLDOWN:
                raise AdmissionConflictError()
            lock = request.lock_version
            request.last_reminded_at = now
            saved = await uow.transcripts.save(request, expected_lock=lock)
            users = await self._users([saved.student_id])
            ref = await self._membership.student(saved.student_id)
            payload = {
                "student_name": full_name(users.get(saved.student_id)),
                "class_name": ref.group_name if ref else "",
                "destination_note": saved.destination_note,
                "request_id_b64": uuid_to_b64(saved.id),
            }
            stamp = int(now.timestamp())
            for officer in await self._notice_to(
                (Role.TRANSCRIPT_OFFICER,),
                saved.student_id,
                Permission.TRANSCRIPTS_FULFIL,
            ):
                uow.notify(
                    NotificationDraft(
                        user_id=officer,
                        type=NotificationType.TRANSCRIPT_REMINDER,
                        payload=payload,
                        dedupe_key=f"transcript:{saved.id}:remind:{officer}:{stamp}",
                    )
                )
            await uow.commit()
        return saved

    async def upload_scan(
        self,
        ctx: AdmissionContext,
        request_id: UUID,
        *,
        name: str,
        data: bytes,
    ) -> DocumentView:
        """Attach the scanned transcript (a confidential document) to the request."""
        if self._files is None:
            raise AdmissionNotFoundError()
        async with self._uow() as uow:
            request = await self._load(uow, request_id)
            await self._access.require(
                ctx,
                request.student_id,
                Permission.TRANSCRIPTS_FULFIL,
                object_type="transcript",
                object_id=request.id,
            )
            file = await self._files.store_bytes(
                owner_id=request.student_id,
                scope=FileScope.STUDENT,
                purpose=FilePurpose.ADMISSION_DOCUMENT,
                name=name,
                data=data,
                confidential=True,
            )
            doc = None
            if request.document_id is not None:
                doc = await uow.documents.get(request.document_id)
            if doc is None:
                doc = await uow.documents.add(
                    DocumentRecord(
                        id=new_id(),
                        student_id=request.student_id,
                        kind="transcript",
                        visibility="confidential",
                        uploaded_by=ctx.user_id,
                        owner_kind="institution",
                    )
                )
            lock = doc.lock_version
            doc.current_version += 1
            await uow.documents.add_version(
                DocumentVersionRecord(
                    document_id=doc.id,
                    version=doc.current_version,
                    file_id=file.id,
                    scan_status="unscanned",
                    uploaded_by=ctx.user_id,
                )
            )
            doc = await uow.documents.save(doc, expected_lock=lock)
            if request.document_id != doc.id:
                request.document_id = doc.id
                await uow.transcripts.save(request, expected_lock=request.lock_version)
            users = await self._users([request.student_id])
            overseers = await permitted_staff(
                self._identity,
                self._uow,
                self._access,
                _OVERSEE_ROLES,
                request.student_id,
                Permission.TRANSCRIPTS_OVERSEE,
            )
            for staff_id in overseers:
                uow.notify(
                    NotificationDraft(
                        user_id=staff_id,
                        type=NotificationType.TRANSCRIPT_SCAN_UPLOADED,
                        payload={
                            "student_name": full_name(users.get(request.student_id)),
                            "student_id": str(request.student_id),
                        },
                        dedupe_key=(
                            f"transcript:{doc.id}:scan:{doc.current_version}:{staff_id}"
                        ),
                    )
                )
            versions = await uow.documents.versions(doc.id)
            await uow.commit()
        return DocumentView(doc, versions, [], False)

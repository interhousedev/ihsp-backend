"""Use cases of consultations: a student asks a counselor or a mentor to talk."""

import dataclasses
import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from app.modules.admission.application.access import VIEWED, AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.consultations import (
    ACTIVE,
    STATUSES,
    Consultation,
    ConsultFormat,
    LinkedKind,
    WithKind,
    check_new,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.ports.consultations import ConsultUnitOfWork
from app.modules.admission.ports.repositories import AuditEvent
from app.shared.actor import Role
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType

ConsultUowFactory = Callable[[], ConsultUnitOfWork]
Viewer = Literal["student", "staff"]

_STUDENT_ACTIONS: Final = {
    "requested": ("cancel",),
    "proposed": ("confirm", "reject", "cancel"),
    "accepted": ("cancel",),
}
_STAFF_ACTIONS: Final = {
    "requested": ("accept", "propose", "decline"),
    "proposed": ("accept", "decline", "cancel"),
    "accepted": ("complete", "propose", "cancel"),
}


@dataclass(frozen=True, slots=True)
class ConsultationDraft:
    """The fields of a new request."""

    with_kind: WithKind
    topic: str
    format: ConsultFormat
    linked_kind: LinkedKind = "other"
    linked_id: UUID | None = None
    details: str = ""
    preferred_times: tuple[dt.datetime, ...] = ()


@dataclass(frozen=True, slots=True)
class ConsultationView:
    """A consultation with what the viewer can do with it."""

    consultation: Consultation
    viewer: Viewer
    actions: tuple[str, ...]
    student_name: str = ""


class ConsultationService:
    """Requests, answers and scheduling of consultations."""

    def __init__(
        self,
        uow_factory: ConsultUowFactory,
        access: AccessPolicy,
        clock: Clock,
        identity: IdentityDirectory | None = None,
    ) -> None:
        """Keep the collaborators."""
        self._identity = identity
        self._uow = uow_factory
        self._access = access
        self._clock = clock

    # - - - Who is who - - -

    def staff_kinds(self, ctx: AdmissionContext) -> frozenset[str]:
        """The kinds of consultation the caller may answer (empty: not staff)."""
        roles = ctx.actor.roles
        if Role.ADMIN in roles:
            return frozenset({"counselor", "mentor"})
        return frozenset(
            kind
            for kind, role in (("counselor", Role.COUNSELOR), ("mentor", Role.MENTOR))
            if role in roles
        )

    def _may_answer(self, ctx: AdmissionContext, c: Consultation) -> bool:
        """Role and claim check only; `_reaches` adds the assignment scope."""
        if Role.ADMIN in ctx.actor.roles:
            return True
        if c.with_kind not in self.staff_kinds(ctx):
            return False
        return c.staff_id in (None, ctx.user_id)

    async def _require_student(self, ctx: AdmissionContext) -> None:
        await self._access.require(ctx, ctx.user_id, Permission.PROFILE_READ)

    def _view(self, ctx: AdmissionContext, c: Consultation) -> ConsultationView:
        if c.student_id == ctx.user_id:
            return ConsultationView(c, "student", _STUDENT_ACTIONS.get(c.status, ()))
        if not self._may_answer(ctx, c):
            raise AdmissionNotFoundError()
        return ConsultationView(c, "staff", _STAFF_ACTIONS.get(c.status, ()))

    async def _load(
        self, uow: ConsultUnitOfWork, consultation_id: UUID
    ) -> Consultation:
        c = await uow.consultations.get(consultation_id)
        if c is None:
            raise AdmissionNotFoundError()
        return c

    # - - - Audit, notifications, linked item - - -

    async def _check_link(
        self,
        uow: ConsultUnitOfWork,
        student_id: UUID,
        kind: LinkedKind,
        linked_id: UUID | None,
    ) -> None:
        """A linked item must be the student's own; anything else is a 404."""
        if linked_id is None:
            return
        owner: UUID | None = None
        if kind in ("project", "activity"):
            item = await uow.items.get(linked_id)
            owner = item.student_id if item else None
        elif kind == "essay":
            essay = await uow.essays.get(linked_id)
            owner = essay.student_id if essay else None
        if owner != student_id:
            raise AdmissionNotFoundError()

    async def _notify_assigned(
        self, uow: ConsultUnitOfWork, ctx: AdmissionContext, c: Consultation
    ) -> None:
        """Tell the counselors or mentors assigned to the student about a request."""
        now = self._clock.now()
        groups = (await self._access.student_facts(c.student_id)).group_ids
        found: set[UUID] = set()
        for scope in ("all", "cohort", "student"):
            for a in await uow.staff.live_assignments(c.with_kind, scope):
                if a.active_at(now) and a.covers(c.student_id, groups):
                    found.add(a.user_id)
        for user_id in sorted(found - {ctx.user_id}):
            uow.notify(
                NotificationDraft(
                    user_id=user_id,
                    type=NotificationType.ADMISSION_HELP_REQUESTED,
                    payload={
                        "kind": "consultation",
                        "event": "requested",
                        "consultation_id": str(c.id),
                        "topic": c.topic,
                        "staff": True,
                    },
                    dedupe_key=f"consult:{c.id}:requested:{user_id}",
                )
            )

    def _record(
        self,
        uow: ConsultUnitOfWork,
        ctx: AdmissionContext,
        c: Consultation,
        event: str,
        *,
        target: UUID | None = None,
    ) -> None:
        """Audit the step and tell the other side (the staff member once known).

        `target` overrides the staff member for steps that clear the claim.
        """
        uow.access.audit(
            AuditEvent(
                action=f"consultation.{event}",
                actor_id=ctx.user_id,
                student_id=c.student_id,
                object_type="consultation",
                object_id=c.id,
                meta={"with_kind": c.with_kind, "status": c.status},
            )
        )
        by_student = ctx.user_id == c.student_id
        if by_student:
            target = target or c.staff_id
        else:
            target = c.student_id
        if target is None or target == ctx.user_id:
            return
        uow.notify(
            NotificationDraft(
                user_id=target,
                type=(
                    NotificationType.ADMISSION_HELP_REQUESTED
                    if by_student
                    else NotificationType.ADMISSION_HELP_RESPONDED
                ),
                payload={
                    "kind": "consultation",
                    "event": event,
                    "consultation_id": str(c.id),
                    "topic": c.topic,
                    "staff": by_student,
                },
                dedupe_key=f"consult:{c.id}:{event}:{c.lock_version}",
            )
        )

    # - - - Student - - -

    async def request(
        self, ctx: AdmissionContext, draft: ConsultationDraft
    ) -> ConsultationView:
        """Ask a counselor or a mentor for a consultation."""
        await self._require_student(ctx)
        now = self._clock.now()
        async with self._uow() as uow:
            check_new(
                draft.topic,
                draft.details,
                draft.preferred_times,
                await uow.consultations.count_active(ctx.user_id),
                now,
            )
            await self._check_link(uow, ctx.user_id, draft.linked_kind, draft.linked_id)
            saved = await uow.consultations.add(
                Consultation(
                    id=new_id(),
                    student_id=ctx.user_id,
                    with_kind=draft.with_kind,
                    topic=draft.topic.strip(),
                    linked_kind=draft.linked_kind,
                    linked_id=draft.linked_id,
                    details=draft.details.strip(),
                    preferred_times=tuple(sorted(draft.preferred_times)),
                    format=draft.format,
                )
            )
            self._record(uow, ctx, saved, "requested")
            await self._notify_assigned(uow, ctx, saved)
            await uow.commit()
        return self._view(ctx, saved)

    async def mine(self, ctx: AdmissionContext) -> list[ConsultationView]:
        """The caller's own requests, newest first."""
        await self._require_student(ctx)
        async with self._uow() as uow:
            rows = await uow.consultations.of_student(ctx.user_id)
        return [self._view(ctx, c) for c in rows]

    async def confirm(self, ctx: AdmissionContext, cid: UUID) -> ConsultationView:
        """Accept the time staff proposed."""
        return await self._student_step(ctx, cid, "confirmed", Consultation.confirm)

    async def reject(self, ctx: AdmissionContext, cid: UUID) -> ConsultationView:
        """Turn the proposed time down; the request goes back to the queue."""
        return await self._student_step(
            ctx, cid, "rejected", Consultation.reject_proposal
        )

    async def _student_step(
        self,
        ctx: AdmissionContext,
        cid: UUID,
        event: str,
        step: Callable[[Consultation], None],
    ) -> ConsultationView:
        await self._require_student(ctx)
        async with self._uow() as uow:
            c = await self._load(uow, cid)
            if c.student_id != ctx.user_id:
                raise AdmissionNotFoundError()
            staff_id = c.staff_id
            step(c)
            saved = await uow.consultations.save(c)
            self._record(uow, ctx, saved, event, target=staff_id)
            await uow.commit()
        return self._view(ctx, saved)

    async def cancel(self, ctx: AdmissionContext, cid: UUID) -> ConsultationView:
        """The student or the answering staff member withdraws the consultation."""
        async with self._uow() as uow:
            c = await self._load(uow, cid)
            if c.student_id != ctx.user_id and not await self._reaches(ctx, c):
                raise AdmissionNotFoundError()
            c.cancel()
            saved = await uow.consultations.save(c)
            self._record(uow, ctx, saved, "cancelled")
            await uow.commit()
        return self._view(ctx, saved)

    # - - - Staff - - -

    async def queue(
        self, ctx: AdmissionContext, statuses: tuple[str, ...] | None = None
    ) -> list[ConsultationView]:
        """Open requests of the caller's kinds plus the ones they answer."""
        kinds = self.staff_kinds(ctx)
        if not kinds:
            raise AdmissionForbiddenError(params={"permission": "consultations:answer"})
        wanted = tuple(s for s in (statuses or ACTIVE) if s in STATUSES)
        async with self._uow() as uow:
            rows = await uow.consultations.for_staff(
                kinds,
                ctx.user_id,
                wanted,
                all_staff=Role.ADMIN in ctx.actor.roles,
            )
        visible = [c for c in rows if await self._reaches(ctx, c)]
        if visible:
            async with self._uow() as uow:
                for c in visible:
                    self._audit_view(uow, ctx, c)
                await uow.commit()
        views = [self._view(ctx, c) for c in visible]
        return await self._with_names(views)

    async def _with_names(
        self, views: list[ConsultationView]
    ) -> list[ConsultationView]:
        """Attach each student's display name for the staff queue."""
        ids = list({v.consultation.student_id for v in views})
        if self._identity is None or not ids:
            return views
        users = await self._identity.get_users(ids)
        names = {i: f"{u.last_name} {u.first_name}".strip() for i, u in users.items()}
        return [
            dataclasses.replace(
                v, student_name=names.get(v.consultation.student_id, "")
            )
            for v in views
        ]

    async def _reaches(self, ctx: AdmissionContext, c: Consultation) -> bool:
        """Return whether the caller may handle the request.

        Admin, or a live assignment of the requested kind covering the student
        (mentors need both opt-ins).
        """
        if c.student_id == ctx.user_id or not self._may_answer(ctx, c):
            return False
        if Role.ADMIN in ctx.actor.roles:
            return True
        res = await self._access.resolve(ctx, c.student_id)
        if not res.in_scope:
            return False
        via = set(res.via)
        return any(a.role.kind == c.with_kind for a in ctx.assignments if a.id in via)

    @staticmethod
    def _audit_view(
        uow: ConsultUnitOfWork, ctx: AdmissionContext, c: Consultation
    ) -> None:
        uow.access.audit(
            AuditEvent(
                action=VIEWED,
                actor_id=ctx.user_id,
                student_id=c.student_id,
                object_type="consultation",
                object_id=c.id,
                meta={"with_kind": c.with_kind},
            )
        )

    async def _staff_step(
        self,
        ctx: AdmissionContext,
        cid: UUID,
        event: str,
        step: Callable[[Consultation, dt.datetime], None],
    ) -> ConsultationView:
        if not self.staff_kinds(ctx):
            raise AdmissionForbiddenError(params={"permission": "consultations:answer"})
        now = self._clock.now()
        async with self._uow() as uow:
            c = await self._load(uow, cid)
            if not await self._reaches(ctx, c):
                raise AdmissionNotFoundError()
            step(c, now)
            saved = await uow.consultations.save(c)
            self._record(uow, ctx, saved, event)
            await uow.commit()
        return self._view(ctx, saved)

    async def accept(
        self,
        ctx: AdmissionContext,
        cid: UUID,
        at: dt.datetime | None,
        location: str,
    ) -> ConsultationView:
        """Take a request; `at` defaults to the first preferred time."""
        return await self._staff_step(
            ctx,
            cid,
            "accepted",
            lambda c, now: c.accept(ctx.user_id, at, location, now),
        )

    async def propose(
        self, ctx: AdmissionContext, cid: UUID, at: dt.datetime, location: str
    ) -> ConsultationView:
        """Offer another time."""
        return await self._staff_step(
            ctx,
            cid,
            "proposed",
            lambda c, now: c.propose(ctx.user_id, at, location, now),
        )

    async def decline(
        self, ctx: AdmissionContext, cid: UUID, reason: str
    ) -> ConsultationView:
        """Decline a request."""
        return await self._staff_step(
            ctx, cid, "declined", lambda c, now: c.decline(ctx.user_id, reason)
        )

    async def complete(
        self, ctx: AdmissionContext, cid: UUID, notes: str
    ) -> ConsultationView:
        """Close an accepted consultation with notes."""
        return await self._staff_step(
            ctx, cid, "completed", lambda c, now: c.complete(notes, now)
        )

"""Comments on a student's items and profile sections."""

from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    CharLimitError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.staff import COMMENT_PERMISSION, Comment
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType

MAX_BODY = 2000
INBOX_LIMIT = 100
STUDENT_VISIBLE = "student_and_staff"
STAFF_ONLY = "staff_only"


def comment_path(target_kind: str, target_id: UUID) -> str:
    """Return the student-side page of a comment target."""
    if target_kind == "item":
        return f"/items/view/?id={target_id}"
    if target_kind == "essay":
        return f"/essays/edit/?id={target_id}"
    return "/"


class CommentService:
    """Writes and reads comments; staff-only notes never reach the student."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        clock: Clock,
        identity: IdentityDirectory | None = None,
    ) -> None:
        """Keep the collaborators."""
        self._identity = identity
        self._uow = uow_factory
        self._access = access
        self._clock = clock

    async def _may(
        self,
        ctx: AdmissionContext,
        student_id: UUID,
        target_kind: str,
        target_id: UUID,
    ) -> tuple[bool, bool]:
        """Return (is_owner, may_see_staff_only) or raise 404/403."""
        permission = COMMENT_PERMISSION.get(target_kind)
        if permission is None:
            raise AdmissionNotFoundError()
        resolution = await self._access.resolve(ctx, student_id)
        if not resolution.in_scope:
            raise AdmissionNotFoundError()
        if resolution.owner:
            return True, False
        done = await self._access.require(
            ctx, student_id, permission, object_type=target_kind, object_id=target_id
        )
        return False, Permission.NOTES_STAFF in done.permissions

    async def thread(
        self,
        ctx: AdmissionContext,
        student_id: UUID,
        target_kind: str,
        target_id: UUID,
    ) -> list[Comment]:
        """Return the comments of a target the caller may see."""
        _, staff_notes = await self._may(ctx, student_id, target_kind, target_id)
        async with self._uow() as uow:
            rows = await uow.comments.for_target(student_id, target_kind, target_id)
        return [c for c in rows if c.visibility == STUDENT_VISIBLE or staff_notes]

    async def inbox(self, ctx: AdmissionContext) -> list[Comment]:
        """Return comments others left for the caller (a student)."""
        async with self._uow() as uow:
            return await uow.comments.inbox(ctx.user_id, INBOX_LIMIT)

    async def add(
        self,
        ctx: AdmissionContext,
        student_id: UUID,
        target_kind: str,
        target_id: UUID,
        body: str,
        visibility: str = STUDENT_VISIBLE,
        anchor: dict[str, object] | None = None,
    ) -> Comment:
        """Add a comment; `staff_only` needs `notes:staff`."""
        text = body.strip()
        if not text or len(text) > MAX_BODY:
            raise CharLimitError(params={"field": "body", "limit": MAX_BODY})
        owner, staff_notes = await self._may(ctx, student_id, target_kind, target_id)
        if visibility not in (STUDENT_VISIBLE, STAFF_ONLY):
            raise AdmissionNotFoundError()
        if visibility == STAFF_ONLY and not staff_notes:
            raise AdmissionForbiddenError(
                params={"permission": Permission.NOTES_STAFF.value}
            )
        async with self._uow() as uow:
            saved = await uow.comments.add(
                Comment(
                    id=new_id(),
                    student_id=student_id,
                    target_kind=target_kind,
                    target_id=target_id,
                    author_id=ctx.user_id,
                    body=text,
                    visibility=visibility,
                    created_at=self._clock.now(),
                    anchor=anchor,
                )
            )
            if not owner and visibility == STUDENT_VISIBLE:
                uow.notify(
                    NotificationDraft(
                        user_id=student_id,
                        type=NotificationType.ADMISSION_COMMENT_ADDED,
                        payload={
                            "author_name": await self._author_name(ctx.user_id),
                            "path": comment_path(target_kind, target_id),
                        },
                        dedupe_key=f"comment:{saved.id}",
                    )
                )
            await uow.commit()
        return saved

    async def _author_name(self, user_id: UUID) -> str:
        if self._identity is None:
            return ""
        ref = (await self._identity.get_users([user_id])).get(user_id)
        return f"{ref.last_name} {ref.first_name}".strip() if ref else ""

    async def delete(self, ctx: AdmissionContext, comment_id: UUID) -> None:
        """Delete a comment the caller wrote, or one on their own profile."""
        async with self._uow() as uow:
            comment = await uow.comments.get(comment_id)
            if comment is None:
                raise AdmissionNotFoundError()
            resolution = await self._access.resolve(ctx, comment.student_id)
            if not resolution.in_scope:
                raise AdmissionNotFoundError()
            own = comment.author_id == ctx.user_id
            visible = comment.visibility == STUDENT_VISIBLE
            if not own and not (resolution.owner and visible):
                raise AdmissionNotFoundError()
            await uow.comments.delete(comment_id, self._clock.now())
            await uow.commit()

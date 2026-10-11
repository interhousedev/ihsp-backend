"""Editing the draft outline under the course row lock."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_course_locked
from app.modules.lms.application.authoring.conflicts import course_conflict
from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.domain.authoring.entities import Course
from app.modules.lms.domain.authoring.hashing import outline_hash
from app.modules.lms.domain.authoring.outline import (
    MoveStep,
    Outline,
    OutlineOp,
    apply_ops,
    step_ids_in,
)
from app.modules.lms.domain.authoring.permissions import EDIT, CourseAccess
from app.modules.lms.ports.authoring.unit_of_work import AuthoringUnitOfWork
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.lms_scopes import MODULES_WRITE


def record_draft_change(
    course: Course, *, outline: Outline | None, actor_id: UUID, now: datetime
) -> None:
    """Bump the lock version and sequence and refresh the outline hash."""
    if outline is not None:
        course.draft_outline = outline
    course.outline_hash = outline_hash(course.draft_meta, course.draft_outline)
    course.lock_version += 1
    course.draft_seq += 1
    course.draft_updated_by = actor_id
    course.draft_updated_at = now


class OutlineEditor:
    """Applies outline operations atomically (LMS-13, spec → Course versioning)."""

    def __init__(self, presenter: Presenter, clock: Clock) -> None:
        """Store collaborators."""
        self.presenter = presenter
        self.clock = clock

    async def apply(
        self,
        uow: AuthoringUnitOfWork,
        actor: Actor,
        course_id: UUID,
        ops: Sequence[OutlineOp],
        *,
        lock_version: int | None,
    ) -> tuple[Course, CourseAccess, list[str]]:
        """Lock the course, check the lock version, apply and save the operations.

        `lock_version=None` skips the check (MCP additions never conflict).
        """
        course = await load_course_locked(uow, course_id)
        access = await access_to(uow, actor, course_id)
        access.require(EDIT)
        access.require_scope(MODULES_WRITE)
        if lock_version is not None and course.lock_version != lock_version:
            raise await course_conflict(self.presenter, uow, course, access)
        known = set(step_ids_in(course.draft_outline))
        known |= await self._course_steps(uow, course_id, ops)
        outline, created = apply_ops(course.draft_outline, ops, course_step_ids=known)
        record_draft_change(
            course, outline=outline, actor_id=actor.user_id, now=self.clock.now()
        )
        await uow.courses.save(course)
        return course, access, created

    @staticmethod
    async def _course_steps(
        uow: AuthoringUnitOfWork, course_id: UUID, ops: Sequence[OutlineOp]
    ) -> set[UUID]:
        """Return which of the moved steps belong to the course."""
        moved = [op.step_id for op in ops if isinstance(op, MoveStep)]
        if not moved:
            return set()
        rows = await uow.steps.get_many(moved)
        return {sid for sid, step in rows.items() if step.course_id == course_id}

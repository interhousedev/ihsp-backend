"""Use case: the curator excludes a student from lessons (approved at once)."""

import datetime as dt
from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.application.excuses.access import ExcuseAccess
from app.modules.academic.application.excuses.notices import ExcuseNotices
from app.modules.academic.application.excuses.ports import (
    ExcuseDirectory,
    ExcuseUowFactory,
)
from app.modules.academic.application.excuses.views import ExcusePresenter, ExcuseView
from app.modules.academic.application.excuses.work_offs import ExcuseWorkOffs
from app.modules.academic.domain.classwork.errors import StudentNotFoundError
from app.modules.academic.domain.excuses.errors import (
    ExcuseNotYoursError,
    ExcuseTemplateNotFoundError,
)
from app.modules.academic.domain.excuses.excuse import (
    REASON_MAX,
    Excuse,
    ExcuseOrigin,
    ExcuseStatus,
    check_period,
)
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.ids import new_id


class CreateExcuseExclusion:
    """Without a start the exclusion begins today and has no end."""

    def __init__(
        self,
        *,
        uow_factory: ExcuseUowFactory,
        clock: Clock,
        directory: ExcuseDirectory,
        access: ExcuseAccess,
        notices: ExcuseNotices,
        work_offs: ExcuseWorkOffs,
        presenter: ExcusePresenter,
    ) -> None:
        """Store the ports."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.directory = directory
        self.access = access
        self.notices = notices
        self.work_offs = work_offs
        self.presenter = presenter

    async def execute(
        self,
        *,
        actor: Actor,
        student_id: UUID,
        template_id: UUID,
        reason: str | None = None,
        starts_on: dt.date | None = None,
        ends_on: dt.date | None = None,
        lesson_ids: Sequence[UUID] = (),
        subject_ids: Sequence[UUID] = (),
    ) -> ExcuseView:
        """Create the approved excuse, make the work-offs and tell the student.

        Raises:
            StudentNotFoundError: the student has no group.
            ExcuseNotYoursError: the actor does not curate the student's group.
            ExcuseTemplateNotFoundError: the template is unknown or switched off.
            ExcuseInvalidError: the period is wrong.
        """
        context = await self.directory.student_context(student_id)
        if context is None:
            raise StudentNotFoundError(params={"student_id": str(student_id)})
        if not await self.access.is_staff_of(student_id, actor):
            raise ExcuseNotYoursError(params={"group_id": str(context.group_id)})
        now = self.clock.now()
        start = starts_on or local_today(self.clock)
        check_period(start, ends_on)
        async with self.uow_factory() as uow:
            templates = await uow.excuses.templates(active_only=True)
            template = next((t for t in templates if t.id == template_id), None)
            if template is None:
                raise ExcuseTemplateNotFoundError(
                    params={"template_id": str(template_id)}
                )
            excuse = Excuse(
                id=new_id(),
                student_id=student_id,
                origin=ExcuseOrigin.CURATOR,
                status=ExcuseStatus.APPROVED,
                template_id=template.id,
                reason=(reason or "").strip()[:REASON_MAX],
                starts_on=start,
                ends_on=ends_on,
                lesson_ids=tuple(dict.fromkeys(lesson_ids)),
                subject_ids=tuple(dict.fromkeys(subject_ids)),
                created_by=actor.user_id,
                decided_by=actor.user_id,
                decided_at=now,
                decision_comment=None,
                version=1,
                created_at=now,
                updated_at=now,
            )
            await uow.excuses.add(excuse)
            people = await self.directory.people([student_id])
            locale = people[student_id].locale if student_id in people else "ru"
            await self.work_offs.for_excuse(
                uow, excuse, locale=locale, assigned_by=actor.user_id
            )
            self.notices.decided(uow, excuse)
            await uow.commit()
            return await self.presenter.detail(uow, excuse)

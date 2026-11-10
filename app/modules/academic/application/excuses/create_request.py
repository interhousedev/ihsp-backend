"""Use case: a student asks for an excuse."""

import datetime as dt
from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.application.excuses.notices import ExcuseNotices
from app.modules.academic.application.excuses.ports import (
    ExcuseDirectory,
    ExcuseUowFactory,
)
from app.modules.academic.application.excuses.views import ExcusePresenter, ExcuseView
from app.modules.academic.domain.classwork.errors import StudentNotFoundError
from app.modules.academic.domain.excuses.attachments import check_attachments
from app.modules.academic.domain.excuses.errors import (
    ExcuseDocumentRequiredError,
    ExcuseTemplateNotFoundError,
)
from app.modules.academic.domain.excuses.excuse import (
    REASON_MAX,
    Excuse,
    ExcuseMessage,
    ExcuseOrigin,
    ExcuseStatus,
    check_period,
    clean_text,
)
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi
from app.shared.ids import new_id


class CreateExcuseRequest:
    """The student's request starts ``pending`` and goes to the curator."""

    def __init__(
        self,
        *,
        uow_factory: ExcuseUowFactory,
        clock: Clock,
        directory: ExcuseDirectory,
        files: FilesApi,
        notices: ExcuseNotices,
        presenter: ExcusePresenter,
    ) -> None:
        """Store the ports."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.directory = directory
        self.files = files
        self.notices = notices
        self.presenter = presenter

    async def execute(
        self,
        *,
        actor: Actor,
        template_id: UUID,
        reason: str,
        starts_on: dt.date,
        ends_on: dt.date | None,
        lesson_ids: Sequence[UUID] = (),
        subject_ids: Sequence[UUID] = (),
        file_ids: Sequence[UUID] = (),
    ) -> ExcuseView:
        """Create the request and tell the curator.

        Raises:
            StudentNotFoundError: the caller has no student record.
            ExcuseTemplateNotFoundError: the template is unknown or switched off.
            ExcuseDocumentRequiredError: the template needs a document.
            ExcuseInvalidError: the reason or the period is wrong.
            ExcuseAttachmentError: a file is not the caller's, ready and allowed.
        """
        context = await self.directory.student_context(actor.user_id)
        if context is None:
            raise StudentNotFoundError(params={"student_id": str(actor.user_id)})
        text = clean_text(reason, REASON_MAX, "reason")
        check_period(starts_on, ends_on)
        found = await self.files.get_many(list(file_ids)) if file_ids else {}
        check_attachments(file_ids, found, actor.user_id)
        now = self.clock.now()
        async with self.uow_factory() as uow:
            templates = await uow.excuses.templates(active_only=True)
            template = next((t for t in templates if t.id == template_id), None)
            if template is None:
                raise ExcuseTemplateNotFoundError(
                    params={"template_id": str(template_id)}
                )
            if template.requires_document and not file_ids:
                raise ExcuseDocumentRequiredError(params={"code": template.code})
            excuse = Excuse(
                id=new_id(),
                student_id=actor.user_id,
                origin=ExcuseOrigin.REQUEST,
                status=ExcuseStatus.PENDING,
                template_id=template.id,
                reason=text,
                starts_on=starts_on,
                ends_on=ends_on,
                lesson_ids=tuple(dict.fromkeys(lesson_ids)),
                subject_ids=tuple(dict.fromkeys(subject_ids)),
                created_by=actor.user_id,
                decided_by=None,
                decided_at=None,
                decision_comment=None,
                version=1,
                created_at=now,
                updated_at=now,
            )
            await uow.excuses.add(excuse)
            if file_ids:
                await uow.excuses.add_message(
                    ExcuseMessage(
                        id=new_id(),
                        excuse_id=excuse.id,
                        author_id=actor.user_id,
                        body="",
                        file_ids=tuple(file_ids),
                        created_at=now,
                    )
                )
            people = await self.directory.people([actor.user_id])
            name = people[actor.user_id].name if actor.user_id in people else ""
            await self.notices.requested(uow, excuse, template, context, name)
            await uow.commit()
            return await self.presenter.detail(uow, excuse)

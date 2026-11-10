"""Handlers of the student's own excuses (`/v1/me/excuse*`)."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.me_excuses.deps import ContainerDep, UserActor
from app.interfaces.http.v1.me_excuses.schemas import (
    ExcuseListOut,
    ExcuseMessageIn,
    ExcuseOut,
    ExcuseRequestIn,
    ExcuseStatusValue,
    ExcuseTemplateListOut,
    ExcuseTemplateOut,
)
from app.modules.academic.domain.excuses.excuse import ExcuseStatus

from fastapi import Query


async def list_templates(
    container: ContainerDep, actor: UserActor
) -> ExcuseTemplateListOut:
    """Active reasons for the request form, in display order."""
    templates = await container.academic.excuses.list_templates.execute()
    return ExcuseTemplateListOut(items=[ExcuseTemplateOut.of(t) for t in templates])


async def list_mine(
    container: ContainerDep,
    actor: UserActor,
    status: Annotated[ExcuseStatusValue | None, Query()] = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> ExcuseListOut:
    """The caller's excuses, newest first."""
    items, next_cursor = await container.academic.excuses.list_excuses.mine(
        actor=actor,
        status=ExcuseStatus(status) if status else None,
        cursor=cursor,
    )
    return ExcuseListOut(
        items=[ExcuseOut.of(v) for v in items], next_cursor=next_cursor
    )


async def request_excuse(
    body: ExcuseRequestIn, container: ContainerDep, actor: UserActor
) -> ExcuseOut:
    """Ask the curator to excuse absences; the request starts pending."""
    view = await container.academic.excuses.create_request.execute(
        actor=actor,
        template_id=body.template_id,
        reason=body.reason,
        starts_on=body.starts_on,
        ends_on=body.ends_on,
        lesson_ids=body.lesson_ids,
        subject_ids=body.subject_ids,
        file_ids=body.file_ids,
    )
    return ExcuseOut.of(view)


async def get_mine(
    excuse_id: UUID, container: ContainerDep, actor: UserActor
) -> ExcuseOut:
    """One of the caller's excuses with its thread; a stranger's answers 404."""
    view = await container.academic.excuses.get_excuse.execute(
        actor=actor, excuse_id=excuse_id
    )
    return ExcuseOut.of(view)


async def post_message(
    excuse_id: UUID,
    body: ExcuseMessageIn,
    container: ContainerDep,
    actor: UserActor,
) -> ExcuseOut:
    """Write to the curator; files must be the caller's ready files."""
    view = await container.academic.excuses.post_message.execute(
        actor=actor, excuse_id=excuse_id, body=body.body, file_ids=body.file_ids
    )
    return ExcuseOut.of(view)


async def cancel(
    excuse_id: UUID, container: ContainerDep, actor: UserActor
) -> ExcuseOut:
    """Withdraw a pending request."""
    view = await container.academic.excuses.cancel_excuse.execute(
        actor=actor, excuse_id=excuse_id
    )
    return ExcuseOut.of(view)

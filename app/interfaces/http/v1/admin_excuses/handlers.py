"""Handlers of Administration's view of excuses (`/v1/admin/excuses*`)."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.admin_excuses.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.me_excuses.schemas import (
    ExcuseDecisionIn,
    ExcuseListOut,
    ExcuseMessageIn,
    ExcuseOut,
    ExcuseStatusValue,
)
from app.modules.academic.domain.excuses.excuse import ExcuseStatus

from fastapi import Query


async def list_excuses(
    container: ContainerDep,
    actor: AdminActor,
    status: Annotated[ExcuseStatusValue | None, Query()] = None,
    student_id: Annotated[UUID | None, Query()] = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> ExcuseListOut:
    """Every excuse, newest first."""
    items, next_cursor = await container.academic.excuses.list_excuses.staff(
        actor=actor,
        status=ExcuseStatus(status) if status else None,
        student_id=student_id,
        cursor=cursor,
    )
    return ExcuseListOut(
        items=[ExcuseOut.of(v) for v in items], next_cursor=next_cursor
    )


async def get_excuse(
    excuse_id: UUID, container: ContainerDep, actor: AdminActor
) -> ExcuseOut:
    """One excuse with its thread."""
    view = await container.academic.excuses.get_excuse.execute(
        actor=actor, excuse_id=excuse_id
    )
    return ExcuseOut.of(view)


async def approve(
    excuse_id: UUID,
    body: ExcuseDecisionIn,
    container: ContainerDep,
    actor: AdminActor,
) -> ExcuseOut:
    """Approve a pending request."""
    view = await container.academic.excuses.decide_excuse.execute(
        actor=actor, excuse_id=excuse_id, approve=True, comment=body.comment
    )
    return ExcuseOut.of(view)


async def reject(
    excuse_id: UUID,
    body: ExcuseDecisionIn,
    container: ContainerDep,
    actor: AdminActor,
) -> ExcuseOut:
    """Reject a pending request."""
    view = await container.academic.excuses.decide_excuse.execute(
        actor=actor, excuse_id=excuse_id, approve=False, comment=body.comment
    )
    return ExcuseOut.of(view)


async def post_message(
    excuse_id: UUID,
    body: ExcuseMessageIn,
    container: ContainerDep,
    actor: AdminActor,
) -> ExcuseOut:
    """Write in the thread."""
    view = await container.academic.excuses.post_message.execute(
        actor=actor, excuse_id=excuse_id, body=body.body, file_ids=body.file_ids
    )
    return ExcuseOut.of(view)

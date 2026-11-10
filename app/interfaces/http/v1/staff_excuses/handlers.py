"""Handlers of the curator's excuses (`/v1/staff/excuses*`)."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.me_excuses.schemas import (
    ExcuseDecisionIn,
    ExcuseEndIn,
    ExcuseExclusionIn,
    ExcuseListOut,
    ExcuseMessageIn,
    ExcuseOut,
    ExcuseStatusValue,
)
from app.interfaces.http.v1.staff_excuses.deps import ContainerDep, StaffActor
from app.modules.academic.domain.excuses.excuse import ExcuseStatus

from fastapi import Query


async def list_excuses(
    container: ContainerDep,
    actor: StaffActor,
    status: Annotated[ExcuseStatusValue | None, Query()] = None,
    student_id: Annotated[UUID | None, Query()] = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> ExcuseListOut:
    """Excuses of the students the caller curates (all students for Administration)."""
    items, next_cursor = await container.academic.excuses.list_excuses.staff(
        actor=actor,
        status=ExcuseStatus(status) if status else None,
        student_id=student_id,
        cursor=cursor,
    )
    return ExcuseListOut(
        items=[ExcuseOut.of(v) for v in items], next_cursor=next_cursor
    )


async def create_exclusion(
    body: ExcuseExclusionIn, container: ContainerDep, actor: StaffActor
) -> ExcuseOut:
    """Excuse a student from the curator's side; approved at once."""
    view = await container.academic.excuses.create_exclusion.execute(
        actor=actor,
        student_id=body.student_id,
        template_id=body.template_id,
        reason=body.reason,
        starts_on=body.starts_on,
        ends_on=body.ends_on,
        lesson_ids=body.lesson_ids,
        subject_ids=body.subject_ids,
    )
    return ExcuseOut.of(view)


async def get_excuse(
    excuse_id: UUID, container: ContainerDep, actor: StaffActor
) -> ExcuseOut:
    """One excuse with its thread; a stranger's student answers 404."""
    view = await container.academic.excuses.get_excuse.execute(
        actor=actor, excuse_id=excuse_id
    )
    return ExcuseOut.of(view)


async def approve(
    excuse_id: UUID,
    body: ExcuseDecisionIn,
    container: ContainerDep,
    actor: StaffActor,
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
    actor: StaffActor,
) -> ExcuseOut:
    """Reject a pending request."""
    view = await container.academic.excuses.decide_excuse.execute(
        actor=actor, excuse_id=excuse_id, approve=False, comment=body.comment
    )
    return ExcuseOut.of(view)


async def revoke(
    excuse_id: UUID,
    body: ExcuseDecisionIn,
    container: ContainerDep,
    actor: StaffActor,
) -> ExcuseOut:
    """Withdraw an approved excuse."""
    view = await container.academic.excuses.revoke_excuse.execute(
        actor=actor, excuse_id=excuse_id, comment=body.comment
    )
    return ExcuseOut.of(view)


async def end_excuse(
    excuse_id: UUID, body: ExcuseEndIn, container: ContainerDep, actor: StaffActor
) -> ExcuseOut:
    """Close an approved excuse on a date."""
    view = await container.academic.excuses.end_excuse.execute(
        actor=actor, excuse_id=excuse_id, ends_on=body.ends_on
    )
    return ExcuseOut.of(view)


async def post_message(
    excuse_id: UUID,
    body: ExcuseMessageIn,
    container: ContainerDep,
    actor: StaffActor,
) -> ExcuseOut:
    """Write to the student."""
    view = await container.academic.excuses.post_message.execute(
        actor=actor, excuse_id=excuse_id, body=body.body, file_ids=body.file_ids
    )
    return ExcuseOut.of(view)

"""Handlers of the teacher pages and teacher contacts."""

import datetime as dt
from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.me_teachers.schemas import (
    MyTeacherResponse,
    TeacherSlotResponse,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import NotFoundError
from app.shared.contracts.identity import TeacherContacts

from fastapi import Depends, Query

ContainerDep = Annotated[Container, Depends(get_container)]
StudentActor = Annotated[Actor, Depends(require_roles(Role.STUDENT))]
TeacherActor = Annotated[Actor, Depends(require_roles(Role.TEACHER))]
AdminActor = Annotated[Actor, Depends(require_roles(Role.ADMIN))]


async def get_my_teachers(
    container: ContainerDep, actor: StudentActor
) -> list[MyTeacherResponse]:
    """Teachers of the student's groups with contacts, status and the week."""
    data = await container.academic.schedule.get_my_teachers.execute(actor)
    return [MyTeacherResponse.of(item) for item in data]


async def get_my_teacher(
    teacher_id: UUID, container: ContainerDep, actor: StudentActor
) -> MyTeacherResponse:
    """One teacher of the student: 404 if the teacher does not teach the caller."""
    data = await container.academic.schedule.get_my_teacher.execute(actor, teacher_id)
    return MyTeacherResponse.of(data)


async def get_my_teacher_timetable(
    teacher_id: UUID,
    container: ContainerDep,
    actor: StudentActor,
    from_: Annotated[dt.date | None, Query(alias="from")] = None,
    to: Annotated[dt.date | None, Query()] = None,
) -> list[TeacherSlotResponse]:
    """All lessons of the teacher between two dates (default: a week from today)."""
    slots = await container.academic.schedule.get_teacher_timetable.execute(
        actor, teacher_id, from_, to
    )
    return [TeacherSlotResponse.of(slot) for slot in slots]


async def _read(container: Container, user_id: UUID) -> TeacherContacts:
    prefs = await container.identity.directory.get_preferences(user_id)
    return prefs.contacts


async def _write(
    container: Container, user_id: UUID, body: TeacherContacts
) -> TeacherContacts:
    patch = {"contacts": body.model_dump(mode="json")}
    prefs = await container.identity.commands.update_preferences(user_id, patch)
    return prefs.contacts


async def get_my_contacts(
    container: ContainerDep, actor: TeacherActor
) -> TeacherContacts:
    """The caller's own public contacts."""
    return await _read(container, actor.user_id)


async def put_my_contacts(
    body: TeacherContacts, container: ContainerDep, actor: TeacherActor
) -> TeacherContacts:
    """Replace the caller's public contacts."""
    return await _write(container, actor.user_id, body)


async def _require_teacher(container: Container, user_id: UUID) -> None:
    user = await container.identity.directory.get_user(user_id)
    if user is None or Role.TEACHER not in user.roles:
        raise NotFoundError(params={"user_id": str(user_id)})


async def get_teacher_contacts(
    id: UUID, container: ContainerDep, admin: AdminActor
) -> TeacherContacts:
    """A teacher's public contacts (admin)."""
    await _require_teacher(container, id)
    return await _read(container, id)


async def put_teacher_contacts(
    id: UUID, body: TeacherContacts, container: ContainerDep, admin: AdminActor
) -> TeacherContacts:
    """Replace a teacher's public contacts (admin)."""
    await _require_teacher(container, id)
    return await _write(container, id, body)

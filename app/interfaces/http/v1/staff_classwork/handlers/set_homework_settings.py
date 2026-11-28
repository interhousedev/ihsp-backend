"""``PATCH /v1/staff/lessons/{id}/homework/settings``: the lesson's two switches."""

from uuid import UUID

from app.interfaces.http.v1.staff_classwork.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.staff_classwork.schemas import (
    LessonHomeworkSwitchesBody,
    StaffLessonResponse,
)


async def set_homework_settings(
    id: UUID,
    body: LessonHomeworkSwitchesBody,
    actor: StaffActor,
    container: ContainerDep,
) -> StaffLessonResponse:
    """Open or close submissions and override the notification setting.

    ``notify`` sent as null makes the lesson follow the teacher's setting again;
    an omitted field is kept.
    """
    data = await container.academic.classwork.set_lesson_homework_switches.execute(
        id,
        actor,
        accept_submissions=body.accept_submissions,
        notify=body.notify,
        change_notify="notify" in body.model_fields_set,
    )
    return StaffLessonResponse.model_validate(data)

"""POST /v1/admin/lessons."""

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.lessons.schemas import ExtraLessonInputBody
from app.interfaces.http.v1.admin_schedule.shared_schemas import LessonItemResponse
from app.modules.academic.application.schedule.create_extra_lesson import (
    ExtraLessonInput,
)


async def create_lesson(
    body: ExtraLessonInputBody, container: ContainerDep, actor: AdminActor
) -> LessonItemResponse:
    """Add an extra lesson."""
    item = await container.academic.schedule.create_extra_lesson.execute(
        actor,
        ExtraLessonInput(
            date=body.date,
            period=body.period,
            subject_id=body.subject_id,
            teacher_id=body.teacher_id,
            room_name=body.room_name,
            audience=[(a.group_id, a.subgroup) for a in body.audience],
            topic=body.topic,
        ),
    )
    return LessonItemResponse.model_validate(item)

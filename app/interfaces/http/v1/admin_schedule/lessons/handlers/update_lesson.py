"""PATCH /v1/admin/lessons/{id}."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.lessons.schemas import LessonPatchBody
from app.interfaces.http.v1.admin_schedule.shared_schemas import LessonItemResponse
from app.modules.academic.application.schedule.unset import UNSET
from app.modules.academic.application.schedule.update_lesson import LessonPatch


async def update_lesson(
    lesson_id: UUID,
    body: LessonPatchBody,
    container: ContainerDep,
    actor: AdminActor,
) -> LessonItemResponse:
    """Change one lesson; it is then marked as changed by hand."""
    sent = body.model_fields_set
    patch = LessonPatch(
        status=body.status,
        teacher_id=body.teacher_id if "teacher_id" in sent else UNSET,
        subject_id=body.subject_id,
        room_name=body.room_name if "room_name" in sent else UNSET,
        date=body.date,
        period=body.period,
        topic=body.topic if "topic" in sent else UNSET,
    )
    item = await container.academic.schedule.update_lesson.execute(
        actor, lesson_id, patch
    )
    return LessonItemResponse.model_validate(item)

"""PUT /v1/staff/lessons/{lesson_id}/item-refs."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import Library, TeachingActor
from app.interfaces.http.v1.library.reader.schemas_plans import (
    LessonItemRefResponse,
    SetLessonRefsBody,
)


async def set_lesson_item_refs(
    lesson_id: UUID, body: SetLessonRefsBody, library: Library, actor: TeachingActor
) -> list[LessonItemRefResponse]:
    """Replace the links of the lesson; its topic is never touched."""
    views = await library.reader.set_lesson_item_refs.execute(
        actor, lesson_id, [ref.to_input() for ref in body.refs]
    )
    return [LessonItemRefResponse.from_view(view) for view in views]

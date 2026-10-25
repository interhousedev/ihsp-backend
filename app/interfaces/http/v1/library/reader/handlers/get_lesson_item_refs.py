"""GET /v1/me/lessons/{lesson_id}/item-refs."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import Library, SignedIn
from app.interfaces.http.v1.library.reader.schemas_plans import LessonItemRefResponse


async def get_lesson_item_refs(
    lesson_id: UUID, library: Library, actor: SignedIn
) -> list[LessonItemRefResponse]:
    """The books a lesson follows (its students and teacher)."""
    views = await library.reader.get_lesson_item_refs.execute(actor, lesson_id)
    return [LessonItemRefResponse.from_view(view) for view in views]

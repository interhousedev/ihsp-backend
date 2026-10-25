"""GET /v1/staff/library/book-plans/next?lesson_id."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import Library, TeachingActor
from app.interfaces.http.v1.library.reader.schemas_plans import (
    NextSectionResponse,
    NextSuggestionResponse,
)


async def suggest_next_section(
    lesson_id: UUID, library: Library, actor: TeachingActor
) -> NextSuggestionResponse:
    """The section after the last one linked to an earlier lesson, if any."""
    view = await library.reader.suggest_next_section.execute(actor, lesson_id)
    return NextSuggestionResponse(
        suggestion=NextSectionResponse.from_view(view) if view else None
    )

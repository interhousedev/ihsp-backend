"""GET /v1/manage/library/suggestions/{id}."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import LibrarianActor, Library
from app.interfaces.http.v1.library.materials.schemas_materials import (
    SuggestedBookBody,
)
from app.interfaces.http.v1.library.materials.schemas_moderation import (
    SuggestionDetailResponse,
)


async def get_suggestion(
    suggestion_id: UUID, library: Library, actor: LibrarianActor
) -> SuggestionDetailResponse:
    """One suggestion with the form the suggester filled in."""
    found = await library.materials.get_suggestion.execute(actor, suggestion_id)
    return SuggestionDetailResponse(
        id=found.id,
        title=found.title,
        url=found.url,
        note=found.note,
        status=found.status,
        book=SuggestedBookBody.model_validate(found.details) if found.details else None,
    )

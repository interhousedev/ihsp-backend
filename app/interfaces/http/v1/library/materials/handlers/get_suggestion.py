"""GET /v1/manage/library/suggestions/{id}."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import LibrarianActor, Library
from app.interfaces.http.v1.library.materials.schemas_materials import (
    SuggestedBookBody,
)
from app.interfaces.http.v1.library.materials.schemas_moderation import (
    SuggestionDetailResponse,
    SuggestionFileResponse,
)


async def get_suggestion(
    suggestion_id: UUID, library: Library, actor: LibrarianActor
) -> SuggestionDetailResponse:
    """One suggestion with the form and the file the suggester sent."""
    found = await library.materials.get_suggestion.execute(actor, suggestion_id)
    ref = await library.core.files.get(found.file_id) if found.file_id else None
    return SuggestionDetailResponse(
        id=found.id,
        title=found.title,
        url=found.url,
        note=found.note,
        status=found.status,
        book=SuggestedBookBody.model_validate(found.details) if found.details else None,
        file=(
            SuggestionFileResponse(
                id=ref.id,
                name=ref.name,
                content_type=ref.content_type,
                byte_size=ref.byte_size,
            )
            if ref
            else None
        ),
        reason=found.reason,
        item_id=found.item_id,
        created_at=found.created_at,
    )

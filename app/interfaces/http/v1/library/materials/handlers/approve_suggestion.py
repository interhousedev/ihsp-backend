"""POST /v1/manage/library/suggestions/{id}/approve."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import LibrarianActor, Library
from app.interfaces.http.v1.library.materials.schemas_moderation import (
    ApproveSuggestionBody,
)

from fastapi import Response, status


async def approve_suggestion(
    suggestion_id: UUID,
    body: ApproveSuggestionBody,
    library: Library,
    actor: LibrarianActor,
) -> Response:
    """Link the book saved from the suggestion, hand over its file, notify."""
    await library.materials.approve_suggestion.execute(
        actor, suggestion_id, item_id=body.item_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

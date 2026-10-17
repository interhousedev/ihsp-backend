"""POST /v1/manage/library/suggestions/{id}/{accept|decline}."""

from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.library.deps import LibrarianActor, Library
from app.interfaces.http.v1.library.materials.schemas_moderation import (
    DeclineSuggestionBody,
)

from fastapi import Response, status


async def decide_suggestion(
    suggestion_id: UUID,
    decision: Literal["accept", "decline"],
    library: Library,
    actor: LibrarianActor,
    body: DeclineSuggestionBody | None = None,
) -> Response:
    """Accept or decline a book suggestion; a decline may say why."""
    await library.materials.decide_suggestion.execute(
        actor,
        suggestion_id,
        accept=decision == "accept",
        reason=body.reason if body else None,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

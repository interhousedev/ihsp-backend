"""GET /v1/me/library/suggestions."""

from app.interfaces.http.v1.library.deps import Library, SignedIn
from app.interfaces.http.v1.library.materials.schemas_materials import (
    MySuggestionResponse,
    MySuggestionsResponse,
)


async def list_my_suggestions(
    library: Library, actor: SignedIn
) -> MySuggestionsResponse:
    """The signed-in person's suggestions and their statuses, newest first."""
    found = await library.materials.list_my_suggestions.execute(actor)
    return MySuggestionsResponse(
        items=[MySuggestionResponse.from_entity(row) for row in found]
    )

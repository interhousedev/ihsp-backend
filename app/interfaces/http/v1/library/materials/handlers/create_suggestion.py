"""POST /v1/library/suggestions."""

from app.interfaces.http.v1.library.deps import Library, SignedIn
from app.interfaces.http.v1.library.materials.schemas_materials import SuggestionBody

from fastapi import Response, status


async def create_suggestion(
    body: SuggestionBody, library: Library, actor: SignedIn
) -> Response:
    """Suggest a book; it waits in the librarian queue."""
    await library.materials.create_suggestion.execute(
        actor,
        title=body.title,
        url=body.url,
        file_id=body.file_id,
        note=body.note,
        details=body.book.model_dump(mode="json") if body.book else None,
    )
    return Response(status_code=status.HTTP_201_CREATED)

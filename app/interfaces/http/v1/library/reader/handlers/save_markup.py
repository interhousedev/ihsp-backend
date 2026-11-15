"""PUT /v1/me/library/markup/{item_id}."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import Library, SignedIn
from app.interfaces.http.v1.library.reader.schemas_markup import (
    MarkupBody,
    MarkupResponse,
)


async def save_markup(
    item_id: UUID, body: MarkupBody, library: Library, actor: SignedIn
) -> MarkupResponse:
    """Replace the caller's markup of the item; no shapes at all removes it."""
    markup = await library.reader.save_markup.execute(
        actor,
        item_id,
        file_id=body.file_id,
        pages={
            page: [shape.model_dump() for shape in shapes]
            for page, shapes in body.pages.items()
        },
    )
    return MarkupResponse.from_entity(markup)

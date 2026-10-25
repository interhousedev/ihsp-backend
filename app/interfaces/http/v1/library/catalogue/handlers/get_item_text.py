"""GET /v1/library/items/{id}/text."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.library.catalogue.schemas_catalogue import ItemTextSchema
from app.interfaces.http.v1.library.deps import Library, MaybeSignedIn

from fastapi import Query


async def get_item_text(
    item_id: UUID,
    library: Library,
    actor: MaybeSignedIn,
    page_from: Annotated[int | None, Query(ge=1)] = None,
    page_to: Annotated[int | None, Query(ge=1)] = None,
) -> ItemTextSchema:
    """Pages of extracted text (at most 50 at a time)."""
    pages = await library.catalogue.get_item_text.execute(
        actor, item_id, page_from=page_from, page_to=page_to
    )
    return ItemTextSchema.from_views(pages)

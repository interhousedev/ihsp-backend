"""GET /v1/library/items/{id}/text/search."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.library.catalogue.schemas_catalogue import (
    ItemTextSearchSchema,
)
from app.interfaces.http.v1.library.deps import Library, MaybeSignedIn

from fastapi import Query


async def search_item_text(
    item_id: UUID,
    library: Library,
    actor: MaybeSignedIn,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> ItemTextSearchSchema:
    """Occurrences of `q` in the item's text: page, snippet and where on the page."""
    view = await library.catalogue.search_item_text.execute(
        actor, item_id, q, limit=limit
    )
    return ItemTextSearchSchema.from_view(view)

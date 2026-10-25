"""GET /v1/library/external/unilibrary/{external_id}."""

from typing import Annotated

from app.interfaces.http.v1.library.catalogue.schemas_items import ItemCardSchema
from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, SignedIn

from fastapi import Path, Query


async def get_unilibrary_record(
    external_id: Annotated[str, Path(max_length=40)],
    library: Library,
    actor: SignedIn,
    accept_language: AcceptLanguage = None,
    category: Annotated[int, Query(ge=1, le=4)] = 1,
) -> ItemCardSchema:
    """The card of one record; the stored card when it is pinned."""
    card = await library.external.get_card.execute(
        actor, external_id, category=category, accept_language=accept_language
    )
    return ItemCardSchema.from_view(card)

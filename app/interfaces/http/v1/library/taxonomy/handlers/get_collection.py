"""GET /v1/library/collections/{collection_id}."""

from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, MaybeSignedIn
from app.interfaces.http.v1.library.taxonomy.schemas_taxonomy import (
    CollectionDetailResponse,
)


async def get_collection(
    collection_id: str,
    library: Library,
    actor: MaybeSignedIn,
    accept_language: AcceptLanguage = None,
) -> CollectionDetailResponse:
    """A published collection (by id or slug) with the cards the caller can see."""
    view = await library.taxonomy.get_collection.execute(
        actor, collection_id, accept_language=accept_language
    )
    return CollectionDetailResponse.from_detail(view)

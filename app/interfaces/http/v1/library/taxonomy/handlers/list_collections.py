"""GET /v1/library/collections."""

from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, MaybeSignedIn
from app.interfaces.http.v1.library.taxonomy.schemas_taxonomy import (
    CollectionResponse,
)


async def list_collections(
    library: Library, actor: MaybeSignedIn, accept_language: AcceptLanguage = None
) -> list[CollectionResponse]:
    """Published collections with the number of items the caller can see."""
    views = await library.taxonomy.list_collections.execute(
        actor, accept_language=accept_language
    )
    return [CollectionResponse.from_view(view) for view in views]

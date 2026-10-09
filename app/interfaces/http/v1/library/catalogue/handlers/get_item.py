"""GET /v1/library/items/{id_or_slug}."""

from app.interfaces.http.v1.library.catalogue.schemas_items import ItemDetailSchema
from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, MaybeSignedIn


async def get_item(
    id_or_slug: str,
    library: Library,
    actor: MaybeSignedIn,
    accept_language: AcceptLanguage = None,
) -> ItemDetailSchema:
    """The item page; `library/not-found` for anything the caller may not see."""
    view = await library.catalogue.get_item.execute(
        actor, id_or_slug, accept_language=accept_language
    )
    return ItemDetailSchema.from_view(view)

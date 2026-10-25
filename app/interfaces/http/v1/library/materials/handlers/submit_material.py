"""POST /v1/library/materials/{id}/submit."""

from uuid import UUID

from app.interfaces.http.v1.library.catalogue.schemas_items import ItemDetailSchema
from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, SignedIn
from app.interfaces.http.v1.library.materials.locale import locale_for


async def submit_material(
    item_id: UUID,
    library: Library,
    actor: SignedIn,
    accept_language: AcceptLanguage = None,
) -> ItemDetailSchema:
    """`pending_review`, or `published` at once for teachers and Administration."""
    locale = await locale_for(library, actor, accept_language)
    view = await library.materials.submit_material.execute(
        actor, item_id, locale=locale
    )
    return ItemDetailSchema.from_view(view)

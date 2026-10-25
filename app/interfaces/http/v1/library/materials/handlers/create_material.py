"""POST /v1/library/materials."""

from app.interfaces.http.v1.library.catalogue.schemas_items import ItemDetailSchema
from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, SignedIn
from app.interfaces.http.v1.library.materials.locale import locale_for
from app.interfaces.http.v1.library.materials.schemas_materials import MaterialInputBody


async def create_material(
    body: MaterialInputBody,
    library: Library,
    actor: SignedIn,
    accept_language: AcceptLanguage = None,
) -> ItemDetailSchema:
    """Start a draft material of the caller."""
    locale = await locale_for(library, actor, accept_language)
    view = await library.materials.create_material.execute(
        actor, body.to_data(), locale=locale
    )
    return ItemDetailSchema.from_view(view)

"""POST /v1/library/materials/{id}/versions."""

from uuid import UUID

from app.interfaces.http.v1.library.catalogue.schemas_items import ItemDetailSchema
from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, SignedIn
from app.interfaces.http.v1.library.materials.locale import locale_for
from app.interfaces.http.v1.library.materials.schemas_materials import MaterialInputBody


async def create_material_version(
    item_id: UUID,
    body: MaterialInputBody,
    library: Library,
    actor: SignedIn,
    accept_language: AcceptLanguage = None,
) -> ItemDetailSchema:
    """A new draft that replaces the published material once it is approved."""
    locale = await locale_for(library, actor, accept_language)
    view = await library.materials.create_material_version.execute(
        actor, item_id, body.to_data(), locale=locale
    )
    return ItemDetailSchema.from_view(view)

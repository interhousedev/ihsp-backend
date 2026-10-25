"""PATCH /v1/library/materials/{id}."""

from uuid import UUID

from app.interfaces.http.v1.library.catalogue.schemas_items import ItemDetailSchema
from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, SignedIn
from app.interfaces.http.v1.library.materials.locale import locale_for
from app.interfaces.http.v1.library.materials.schemas_materials import MaterialPatchBody


async def update_material(
    item_id: UUID,
    body: MaterialPatchBody,
    library: Library,
    actor: SignedIn,
    accept_language: AcceptLanguage = None,
) -> ItemDetailSchema:
    """Change title, description, topics or text; the status stays."""
    locale = await locale_for(library, actor, accept_language)
    view = await library.materials.update_material.execute(
        actor, item_id, body.to_patch(), locale=locale
    )
    return ItemDetailSchema.from_view(view)

"""POST /v1/library/materials/{id}/files."""

from uuid import UUID

from app.interfaces.http.v1.library.catalogue.schemas_items import ItemDetailSchema
from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, SignedIn
from app.interfaces.http.v1.library.materials.locale import locale_for
from app.interfaces.http.v1.library.materials.schemas_materials import (
    MaterialFilesBody,
)


async def attach_material_files(
    item_id: UUID,
    body: MaterialFilesBody,
    library: Library,
    actor: SignedIn,
    accept_language: AcceptLanguage = None,
) -> ItemDetailSchema:
    """One PDF, or up to 20 photos, uploaded with the purpose `library_material`."""
    locale = await locale_for(library, actor, accept_language)
    view = await library.materials.attach_material_files.execute(
        actor, item_id, body.file_ids, locale=locale
    )
    return ItemDetailSchema.from_view(view)

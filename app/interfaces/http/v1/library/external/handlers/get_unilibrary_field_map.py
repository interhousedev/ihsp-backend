"""GET /v1/admin/library/unilibrary/field-map."""

from app.interfaces.http.v1.library.deps import AdminActor, Library
from app.interfaces.http.v1.library.external.schemas_external import (
    FieldMapEntrySchema,
)


async def get_unilibrary_field_map(
    library: Library, actor: AdminActor
) -> list[FieldMapEntrySchema]:
    """Which UniLibrary field is which subject."""
    entries = await library.external.get_field_map.execute(actor)
    return [FieldMapEntrySchema.from_entity(entry) for entry in entries]

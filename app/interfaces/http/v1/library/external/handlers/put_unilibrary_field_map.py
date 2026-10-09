"""PUT /v1/admin/library/unilibrary/field-map."""

from app.interfaces.http.v1.library.deps import AdminActor, Library
from app.interfaces.http.v1.library.external.schemas_external import (
    FieldMapEntrySchema,
)


async def put_unilibrary_field_map(
    body: list[FieldMapEntrySchema], library: Library, actor: AdminActor
) -> list[FieldMapEntrySchema]:
    """Replace the whole map."""
    entries = await library.external.put_field_map.execute(
        actor, [entry.to_entity() for entry in body]
    )
    return [FieldMapEntrySchema.from_entity(entry) for entry in entries]

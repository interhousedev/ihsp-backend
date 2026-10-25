"""GET /v1/admin/library/unilibrary/settings."""

from app.interfaces.http.v1.library.deps import AdminActor, Library
from app.interfaces.http.v1.library.external.schemas_external import (
    UniLibrarySettingsResponse,
)


async def get_unilibrary_settings(
    library: Library, actor: AdminActor
) -> UniLibrarySettingsResponse:
    """The effective switches (the override, else the environment)."""
    flags = await library.external.get_settings.execute(actor)
    return UniLibrarySettingsResponse.from_flags(flags)

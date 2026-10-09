"""PUT /v1/admin/library/unilibrary/settings."""

from app.interfaces.http.v1.library.deps import AdminActor, Library
from app.interfaces.http.v1.library.external.schemas_external import (
    UniLibrarySettingsBody,
    UniLibrarySettingsResponse,
)


async def put_unilibrary_settings(
    body: UniLibrarySettingsBody, library: Library, actor: AdminActor
) -> UniLibrarySettingsResponse:
    """Switch UniLibrary on or off at runtime."""
    flags = await library.external.put_settings.execute(
        actor, enabled=body.enabled, anonymous_cards=body.anonymous_cards
    )
    return UniLibrarySettingsResponse.from_flags(flags)

"""GET /v1/admin/library/unilibrary/status."""

from app.interfaces.http.v1.library.deps import AcceptLanguage, AdminActor, Library
from app.interfaces.http.v1.library.external.schemas_external import (
    UniLibraryStatusResponse,
)


async def get_unilibrary_status(
    library: Library, actor: AdminActor, accept_language: AcceptLanguage = None
) -> UniLibraryStatusResponse:
    """Breaker state, last calls, cache counters and hidden records."""
    view = await library.external.get_status.execute(actor, accept_language)
    return UniLibraryStatusResponse.from_view(view)

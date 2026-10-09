"""GET /v1/me/library."""

from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, SignedIn
from app.interfaces.http.v1.library.reader.schemas_reader import MeLibraryResponse
from app.modules.library.application.locale import resolve_locale


async def get_me_library(
    library: Library, actor: SignedIn, accept_language: AcceptLanguage = None
) -> MeLibraryResponse:
    """Continue reading, shelf counts and the offline limits."""
    locale = await resolve_locale(library.core.identity, actor, accept_language)
    view = await library.reader.get_me_library.execute(actor, locale=locale)
    return MeLibraryResponse.from_view(view)

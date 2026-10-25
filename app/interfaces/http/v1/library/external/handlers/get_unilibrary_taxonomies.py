"""GET /v1/library/external/unilibrary/taxonomies."""

from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, SignedIn
from app.interfaces.http.v1.library.external.schemas_external import (
    UniLibraryTaxonomyResponse,
)


async def get_unilibrary_taxonomies(
    library: Library, actor: SignedIn, accept_language: AcceptLanguage = None
) -> UniLibraryTaxonomyResponse:
    """Types, fields, languages and access options for the search filters."""
    view = await library.external.get_taxonomies.execute(actor, accept_language)
    return UniLibraryTaxonomyResponse.from_view(view)

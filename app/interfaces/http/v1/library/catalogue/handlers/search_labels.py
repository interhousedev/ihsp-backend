"""GET /v1/library/authors and /v1/library/tags: suggestions while typing."""

from app.interfaces.http.v1.library.catalogue.schemas_catalogue import (
    TagSuggestionSchema,
)
from app.interfaces.http.v1.library.deps import Library, MaybeSignedIn, SignedIn

from fastapi import Query


async def search_authors(
    library: Library, actor: SignedIn, q: str = Query(default="", max_length=100)
) -> list[str]:
    """Existing author names that match `q` (Latin and Cyrillic spellings meet)."""
    return await library.catalogue.search_authors.execute(actor, q)


async def search_tags(
    library: Library,
    actor: MaybeSignedIn,
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=8, ge=1, le=50),
) -> list[TagSuggestionSchema]:
    """Existing tags that match `q`, or the most used ones when `q` is empty."""
    found = await library.catalogue.search_tags.execute(actor, q, limit=limit)
    return [TagSuggestionSchema(name=t.name, item_count=t.item_count) for t in found]

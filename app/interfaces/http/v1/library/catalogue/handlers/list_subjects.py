"""GET /v1/library/subjects."""

from app.interfaces.http.v1.library.catalogue.schemas_catalogue import (
    LibrarySubjectSchema,
)
from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, MaybeSignedIn


async def list_subjects(
    library: Library,
    actor: MaybeSignedIn,
    all: bool = False,  # noqa: A002 - the query parameter is named `all`
    accept_language: AcceptLanguage = None,
) -> list[LibrarySubjectSchema]:
    """Subjects with visible items and their counts; `?all=1` lists every subject."""
    views = await library.catalogue.list_subjects.execute(
        actor, include_empty=all, accept_language=accept_language
    )
    return [LibrarySubjectSchema.from_view(view) for view in views]

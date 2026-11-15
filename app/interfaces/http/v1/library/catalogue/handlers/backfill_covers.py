"""POST /v1/manage/library/covers/backfill."""

from app.interfaces.http.v1.library.deps import LibrarianActor, Library


async def backfill_covers(library: Library, actor: LibrarianActor) -> None:
    """Start cutting covers for books without one; manual covers stay."""
    await library.catalogue.backfill_covers.request(actor)

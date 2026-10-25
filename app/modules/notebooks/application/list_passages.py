"""Use case: the passages of a source, page by page (the source viewer, NB-7)."""

from uuid import UUID

from app.modules.notebooks.application.access import load_source
from app.modules.notebooks.domain.entities import Passage
from app.modules.notebooks.domain.limits import PASSAGES_PAGE_DEFAULT, PASSAGES_PAGE_MAX
from app.modules.notebooks.domain.paging import Paged
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.pagination import decode_cursor, encode_cursor


class ListPassages:
    """Reads the passages of the student's source in reading order."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(
        self,
        actor: Actor,
        notebook_id: UUID,
        source_id: UUID,
        cursor: str | None = None,
        limit: int = PASSAGES_PAGE_DEFAULT,
    ) -> Paged[Passage]:
        """Return up to `limit` passages after the cursor (default 60, at most 200).

        Raises:
            NotebookNotFoundError: Notebook or source is not the caller's.
            ValidationFailedError: The cursor is malformed.
        """
        size = min(limit, PASSAGES_PAGE_MAX) if limit > 0 else PASSAGES_PAGE_DEFAULT
        position = decode_cursor(cursor) or {}
        after_seq = _seq_of(position)
        async with self.uow_factory() as uow:
            await load_source(uow, actor.user_id, notebook_id, source_id, write=False)
            found = await uow.passages.list_for_source(
                source_id, after_seq=after_seq, limit=size + 1
            )
        page = found[:size]
        more = len(found) > size
        return Paged(
            items=page,
            next_cursor=encode_cursor({"seq": page[-1].seq}) if more else None,
        )


def _seq_of(position: dict[str, object]) -> int:
    """The `seq` in a cursor (0 for the first page or an unusable value)."""
    seq = position.get("seq", 0)
    return seq if isinstance(seq, int) and seq >= 0 else 0

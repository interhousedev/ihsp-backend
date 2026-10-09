"""Use case: list the student's notebooks, pinned first (NB-2)."""

from datetime import datetime
from uuid import UUID

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.paging import Paged
from app.modules.notebooks.ports.notebook_repository import NotebookCursor
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import ValidationFailedError
from app.shared.pagination import decode_cursor, encode_cursor

DEFAULT_LIMIT = 30
MAX_LIMIT = 100


def encode_notebook_cursor(notebook: Notebook) -> str:
    """The opaque cursor that continues the list after this notebook."""
    opened = notebook.last_opened_at
    return encode_cursor(
        {
            "p": notebook.pinned,
            "o": opened.isoformat() if opened is not None else None,
            "id": str(notebook.id),
        }
    )


def decode_notebook_cursor(cursor: str | None) -> NotebookCursor | None:
    """Read a cursor made by `encode_notebook_cursor`; a broken one is a 422."""
    data = decode_cursor(cursor)
    if data is None:
        return None
    try:
        opened = data["o"]
        pinned = data["p"]
        if not isinstance(pinned, bool):
            raise TypeError("pinned")
        return NotebookCursor(
            pinned=pinned,
            last_opened_at=(
                datetime.fromisoformat(opened) if opened is not None else None
            ),
            id=UUID(data["id"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationFailedError(
            params={"field": "cursor"}, support_details="malformed cursor"
        ) from exc


class ListNotebooks:
    """Pinned notebooks first, then the most recently opened; cursor paginated."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(
        self,
        actor: Actor,
        q: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> Paged[Notebook]:
        """Return one page of the student's live notebooks.

        `q` filters by title (case-insensitive substring); `limit` is kept within
        1 to 100.
        """
        size = max(1, min(limit, MAX_LIMIT))
        after = decode_notebook_cursor(cursor)
        async with self.uow_factory() as uow:
            rows = await uow.notebooks.list_for_owner(
                actor.user_id,
                query=(q or "").strip() or None,
                after=after,
                limit=size + 1,
            )
        page = rows[:size]
        more = len(rows) > size
        return Paged(
            items=page,
            next_cursor=encode_notebook_cursor(page[-1]) if more else None,
        )

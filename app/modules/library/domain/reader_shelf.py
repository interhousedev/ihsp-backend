"""A user's shelf: want to read, reading, finished (LIB-7). Pure rules, no I/O."""

import dataclasses
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.library.domain.enums import ShelfState


@dataclass(frozen=True, slots=True)
class ShelfEntry:
    """An item on a user's shelf; UniLibrary records are links."""

    user_id: UUID
    item_id: UUID
    state: ShelfState
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


def place_on_shelf(
    current: ShelfEntry | None,
    *,
    user_id: UUID,
    item_id: UUID,
    state: ShelfState,
    now: datetime,
) -> ShelfEntry:
    """The entry after putting the item in `state`.

    `finished_at` is set when the entry becomes `done` and cleared when it leaves
    that state; putting the same state again changes nothing.
    """
    if current is None:
        return ShelfEntry(
            user_id=user_id,
            item_id=item_id,
            state=state,
            finished_at=now if state is ShelfState.DONE else None,
            created_at=now,
            updated_at=now,
        )
    if current.state is state:
        return current
    return dataclasses.replace(
        current,
        state=state,
        finished_at=now if state is ShelfState.DONE else None,
        updated_at=now,
    )

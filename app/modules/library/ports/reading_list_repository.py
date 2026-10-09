"""Port: reading lists (taxonomy area)."""

from collections.abc import Collection, Sequence
from typing import Protocol
from uuid import UUID

from app.modules.library.domain.enums import Importance, ListStatus
from app.modules.library.domain.reading_list import ReadingList, ReadingListEntry
from app.shared.contracts.library import ReadingListSummary


class ReadingListRepository(Protocol):
    """Reading lists and their entries."""

    async def lists_for_item(
        self, item_id: UUID, *, group_id: UUID | None, staff: bool
    ) -> list[tuple[UUID, str, Importance]]:
        """Published lists with the item, as `(list id, title, importance)`.

        Staff see every published list; a student sees school and subject lists and
        the lists of their group.
        """
        ...

    async def add(self, reading_list: ReadingList) -> None:
        """Insert a list (entries are separate)."""
        ...

    async def get(self, list_id: UUID, *, lock: bool = False) -> ReadingList | None:
        """The list or None; `lock` takes a row lock for a change."""
        ...

    async def save(self, reading_list: ReadingList) -> None:
        """Update the fields of a list."""
        ...

    async def delete(self, list_id: UUID) -> None:
        """Delete the list and its entries."""
        ...

    async def find(
        self,
        *,
        subject_id: UUID | None = None,
        owner_id: UUID | None = None,
        group_id: UUID | None = None,
        status: ListStatus | None = None,
    ) -> list[ReadingList]:
        """Lists matching every given filter, newest change first.

        `group_id` keeps the lists that name the group. Who may see which list is
        decided by `reading_list_policy.can_view_list`, not here.
        """
        ...

    async def entries(
        self, list_ids: Sequence[UUID]
    ) -> dict[UUID, list[ReadingListEntry]]:
        """Entries of each list by position (empty lists are absent)."""
        ...

    async def replace_entries(
        self, list_id: UUID, entries: Sequence[ReadingListEntry]
    ) -> None:
        """Replace all entries of the list in one step."""
        ...

    async def clear_topic(self, topic_ids: Collection[UUID]) -> int:
        """Forget the topics on entries (a deleted topic); returns the entries changed."""
        ...

    async def summaries_for_subject(
        self, subject_id: UUID, *, group_id: UUID | None
    ) -> list[ReadingListSummary]:
        """Published lists of the subject that the group may see, with entry counts.

        The lists are those with scope `subject` or `school` and the `groups` lists
        that name `group_id`; with `group_id=None` the group lists are left out.
        Entries whose item is not published (or is hidden) are not counted.
        """
        ...

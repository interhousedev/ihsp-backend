"""Port: storage of sources."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import SourceKind, SourceStatus


class SourceRepository(Protocol):
    """Sources in `notebooks.sources`."""

    async def add(self, source: Source) -> None:
        """Insert a new source."""
        ...

    async def get(self, source_id: UUID) -> Source | None:
        """Return the source."""
        ...

    async def get_for_update(self, source_id: UUID) -> Source | None:
        """Return the source and lock its row until the transaction ends."""
        ...

    async def save(self, source: Source) -> None:
        """Write the source's stored fields."""
        ...

    async def delete(self, source_id: UUID) -> None:
        """Delete the source (its passages cascade)."""
        ...

    async def list_for_notebook(self, notebook_id: UUID) -> list[Source]:
        """All sources of a notebook ordered by `position`."""
        ...

    async def get_many(self, source_ids: Sequence[UUID]) -> list[Source]:
        """The sources that exist, in the order of `source_ids`."""
        ...

    async def count_for_notebook(self, notebook_id: UUID) -> int:
        """How many sources the notebook has (any status)."""
        ...

    async def total_chars(self, notebook_id: UUID) -> int:
        """Sum of `char_count` over the notebook's usable (ready/stale) sources."""
        ...

    async def next_position(self, notebook_id: UUID) -> int:
        """`max(position) + 1`, 1 for an empty notebook."""
        ...

    async def ref_key_exists(self, notebook_id: UUID, ref_key: str) -> bool:
        """True if the notebook already has a source with this duplicate key."""
        ...

    async def set_selected(
        self, notebook_id: UUID, selected: bool, ids: Sequence[UUID] | None
    ) -> None:
        """Set the checkbox of the given sources (all of the notebook when None)."""
        ...

    async def list_by_ref_keys(self, ref_keys: Sequence[str]) -> list[Source]:
        """Sources of any notebook with these duplicate keys (not deleted notebooks)."""
        ...

    async def list_for_sweep(
        self,
        kinds: Sequence[SourceKind],
        statuses: Sequence[SourceStatus],
        *,
        after_id: UUID | None,
        limit: int,
    ) -> list[Source]:
        """Sources of the kinds and statuses ordered by id, after `after_id`."""
        ...

    async def stuck_processing(
        self, updated_before: datetime, limit: int
    ) -> list[Source]:
        """Sources in `processing` (or `pending`) not updated since the cutoff."""
        ...

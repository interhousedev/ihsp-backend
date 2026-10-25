"""Fake TermResolver and UsageResolver."""

from collections.abc import Sequence
from datetime import date
from uuid import UUID

from app.modules.files.domain.used_by import UsedBy


class FakeTermResolver:
    """Terms configured by the test: ``current`` and ``ends``."""

    def __init__(self, current: UUID | None = None) -> None:
        """Set the term returned for today."""
        self.current = current
        self.ends: dict[UUID, date] = {}

    async def current_term_id(self, today: date) -> UUID | None:
        """Return the configured current term."""
        return self.current

    async def term_end(self, term_id: UUID) -> date | None:
        """Return the end date of a known term."""
        return self.ends.get(term_id)


class FakeUsageResolver:
    """Usage configured by the test."""

    def __init__(self) -> None:
        """Start with nothing in use."""
        self.usage: dict[UUID, list[UsedBy]] = {}

    async def used_by(self, file_ids: Sequence[UUID]) -> dict[UUID, list[UsedBy]]:
        """Return the configured usage of the given files."""
        return {fid: list(self.usage[fid]) for fid in file_ids if fid in self.usage}

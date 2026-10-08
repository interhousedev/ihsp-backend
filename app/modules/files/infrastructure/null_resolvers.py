"""Fallback resolvers used until I1 connects the academic, links and ai modules."""

from collections.abc import Sequence
from datetime import date
from uuid import UUID

from app.modules.files.domain.used_by import UsedBy


class NoTermResolver:
    """No terms known: student files belong to no term and never expire by term."""

    async def current_term_id(self, today: date) -> UUID | None:
        """Return no term."""
        return None

    async def term_end(self, term_id: UUID) -> date | None:
        """Return no end date."""
        return None


class NoUsageResolver:
    """Nothing is known to use the files."""

    async def used_by(self, file_ids: Sequence[UUID]) -> dict[UUID, list[UsedBy]]:
        """Return an empty usage list for every file."""
        return {}

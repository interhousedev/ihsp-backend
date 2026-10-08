"""Where files are used, resolved through other modules."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.files.domain.used_by import UsedBy


class UsageResolver(Protocol):
    """Implemented by I1 over links and ai."""

    async def used_by(self, file_ids: Sequence[UUID]) -> dict[UUID, list[UsedBy]]:
        """Return the places that refer to each file (missing key = unused)."""
        ...

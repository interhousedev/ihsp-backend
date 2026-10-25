"""Port: published course versions."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.lms.domain.learning.entities import LiveVersion


class VersionRepository(Protocol):
    """Immutable version manifests."""

    async def get(self, version_id: UUID) -> LiveVersion | None:
        """Return a version by id."""
        ...

    async def get_many(self, version_ids: Sequence[UUID]) -> dict[UUID, LiveVersion]:
        """Return the versions with these ids."""
        ...

"""Storage port of the runtime limits: overrides and per-user extensions."""

from typing import Any, Protocol
from uuid import UUID

from app.modules.admin.domain.limits import ExtensionRecord, ExtensionTerms


class LimitStore(Protocol):
    """Reads and writes the overrides and the extensions."""

    async def read_overrides(self) -> dict[str, Any]:
        """Every stored override row, keyed by its ``limit.<name>`` key."""
        ...

    async def write_overrides(
        self, upserts: dict[str, int], deletes: list[str], *, updated_by: UUID
    ) -> None:
        """Insert or update the given keys and delete the others, in one transaction."""
        ...

    async def read_extensions(self) -> list[ExtensionRecord]:
        """Every stored extension."""
        ...

    async def get_extension(self, user_id: UUID) -> ExtensionRecord | None:
        """The extension of one user, if any."""
        ...

    async def save_extension(
        self, user_id: UUID, terms: ExtensionTerms, *, actor_id: UUID
    ) -> None:
        """Insert or replace the extension of a user."""
        ...

    async def delete_extension(self, user_id: UUID) -> bool:
        """Remove the extension of a user; False when there was none."""
        ...

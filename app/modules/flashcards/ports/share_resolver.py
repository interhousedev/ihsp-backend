"""Port: what a share link points at (answered by the links module)."""

from typing import Protocol
from uuid import UUID


class ShareResolver(Protocol):
    """`LinksApi.resolve_share` of the links module (plan § API contract notes)."""

    async def resolve_share(self, slug: str) -> tuple[str, UUID] | None:
        """Return (kind, target_id) of an active share, else None."""
        ...

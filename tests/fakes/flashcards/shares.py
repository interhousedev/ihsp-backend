"""A fake of `LinksApi.resolve_share`."""

from uuid import UUID


class FakeShares:
    """Implements ShareResolver with a dict of slug -> (kind, target id)."""

    def __init__(self) -> None:
        """Start with no shares."""
        self.shares: dict[str, tuple[str, UUID]] = {}

    def add(self, slug: str, kind: str, target_id: UUID) -> None:
        """Make a share active."""
        self.shares[slug] = (kind, target_id)

    async def resolve_share(self, slug: str) -> tuple[str, UUID] | None:
        """Return (kind, target_id) of an active share, else None."""
        return self.shares.get(slug)

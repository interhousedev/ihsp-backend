"""In-memory store of guest answers."""

from app.modules.links.ports.guest_answers import StoredGuestAnswer


class FakeGuestAnswerStore:
    """Keeps answers in a dict; the TTL is recorded, not enforced."""

    def __init__(self) -> None:
        """Start empty."""
        self.items: dict[str, StoredGuestAnswer] = {}
        self.ttls: dict[str, int] = {}

    async def put(
        self, token: str, answer: StoredGuestAnswer, ttl_seconds: int
    ) -> None:
        """Save the answer."""
        self.items[token] = answer
        self.ttls[token] = ttl_seconds

    async def get(self, token: str) -> StoredGuestAnswer | None:
        """Return the answer or None."""
        return self.items.get(token)

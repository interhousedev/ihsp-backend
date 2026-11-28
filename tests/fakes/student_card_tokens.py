"""In-memory fake of StudentCardTokens."""

from uuid import UUID


class FakeStudentCardTokens:
    """Tokens in a dict."""

    def __init__(self) -> None:
        """Start empty."""
        self.by_user: dict[UUID, str] = {}

    async def ensure(self, user_id: UUID, candidate: str) -> str:
        """Keep the first token."""
        return self.by_user.setdefault(user_id, candidate)

    async def replace(self, user_id: UUID, token: str) -> None:
        """Overwrite the token."""
        self.by_user[user_id] = token

    async def owner(self, token: str) -> UUID | None:
        """Look the token up."""
        return next((u for u, t in self.by_user.items() if t == token), None)

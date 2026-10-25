"""A BellSync that records the students it was asked through."""

from uuid import UUID

from app.shared.contracts.emis import EmisUnavailable


class FakeBellSync:
    """Records user ids; students in ``fail_for`` have no working EMIS link."""

    def __init__(self) -> None:
        """Start empty."""
        self.calls: list[UUID] = []
        self.fail_for: set[UUID] = set()

    async def execute(self, user_id: UUID) -> object:
        """Record the call; raise for students without a working link."""
        self.calls.append(user_id)
        if user_id in self.fail_for:
            raise EmisUnavailable()
        return "unchanged"

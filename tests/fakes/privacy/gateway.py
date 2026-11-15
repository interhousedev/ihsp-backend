"""An in-memory ``ErasureGateway`` for the identity tests."""

from dataclasses import dataclass, field
from uuid import UUID

from app.shared.contracts.privacy import ErasureTicket

from uuid_utils.compat import uuid7


@dataclass(slots=True)
class FakeErasureGateway:
    """Records what identity asked privacy to do."""

    requests: list[tuple[UUID, str | None, str | None]] = field(default_factory=list)
    completed: list[UUID] = field(default_factory=list)
    restored_ids: list[UUID] = field(default_factory=list)

    async def request(
        self, user_id: UUID, *, ip: str | None, user_agent: str | None
    ) -> ErasureTicket:
        """Remember the request."""
        self.requests.append((user_id, ip, user_agent))
        return ErasureTicket(request_id=uuid7(), status="pending_review")

    async def complete(self, user_id: UUID) -> None:
        """Remember the completion."""
        self.completed.append(user_id)

    async def restored(self, user_id: UUID) -> None:
        """Remember the restore."""
        self.restored_ids.append(user_id)

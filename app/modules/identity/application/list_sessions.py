"""GET /v1/id/me/sessions: active devices of the caller."""

from dataclasses import dataclass

from app.modules.identity.domain.session import LoginSession
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock


@dataclass(frozen=True, slots=True)
class SessionView:
    """A session and whether it is the one making the request."""

    session: LoginSession
    current: bool


@dataclass(frozen=True, slots=True)
class ListSessions:
    """Lists the caller's active sessions (ID-17)."""

    uow_factory: UowFactory
    clock: Clock

    async def execute(self, actor: Actor) -> list[SessionView]:
        """Most recently used first."""
        async with self.uow_factory() as uow:
            sessions = await uow.sessions.list_active(actor.user_id, self.clock.now())
        return [SessionView(s, current=s.id == actor.session_id) for s in sessions]

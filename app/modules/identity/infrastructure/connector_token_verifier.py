"""Verifies ihsp_mcp_ connector tokens against the database (MCP-5)."""

from datetime import timedelta
from typing import Literal

from app.modules.identity.domain.connector import looks_like_token
from app.modules.identity.domain.scopes import role_may_use_server
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import UnauthorizedError
from app.shared.clock import Clock
from app.shared.ids import hash_token

TOUCH_INTERVAL = timedelta(minutes=1)


def _unauthorized(reason: str) -> UnauthorizedError:
    return UnauthorizedError(support_details=f"connector token: {reason}")


class DbConnectorTokenVerifier:
    """ConnectorTokenVerifier: active connector, active user, allowed role."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Keep the unit of work factory and the clock."""
        self._uow_factory = uow_factory
        self._clock = clock

    async def verify_connector(
        self, token: str, *, server: Literal["student", "lms", "admin"]
    ) -> Actor:
        """Return the actor with connector_id and scopes, or raise UnauthorizedError."""
        if not looks_like_token(token):
            raise _unauthorized("format")
        now = self._clock.now()
        async with self._uow_factory() as uow:
            connector = await uow.connectors.get_by_token_hash(hash_token(token))
            if connector is None or not connector.is_active(now):
                raise _unauthorized("unknown, revoked or expired")
            if connector.server != server:
                raise _unauthorized("wrong server")
            user = await uow.users.get(connector.user_id)
            if user is None or not user.is_active:
                raise _unauthorized("user inactive")
            if not role_may_use_server(user.roles, server):
                raise _unauthorized("role missing")
            await uow.connectors.touch_last_used(
                connector.id, now, min_interval=TOUCH_INTERVAL
            )
            await uow.commit()
            # A course restriction travels as `course:<uuid>` scopes (MCP-5).
            courses = (
                {f"course:{course_id}" for course_id in connector.course_ids}
                if server == "lms" and connector.course_ids
                else set()
            )
            return Actor(
                user_id=user.id,
                roles=frozenset(user.roles),
                connector_id=connector.id,
                scopes=frozenset(connector.scopes) | courses,
            )

"""Fixtures of the identity HTTP tests."""

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_users import ROUTERS as ADMIN_ROUTERS
from app.interfaces.http.v1.id import ROUTERS as ID_ROUTERS
from app.interfaces.http.v1.oauth import ROUTERS as OAUTH_ROUTERS
from app.modules.identity.domain.session import LoginSession
from app.modules.identity.domain.user import User
from app.shared.actor import Actor, Role
from app.shared.base_error import UnauthorizedError
from tests.conftest import HttpClientFactory
from tests.identity.support import World

import pytest
from httpx import AsyncClient

APP_HEADERS = {"Origin": "http://localhost:3002", "X-IHSP-Client": "web"}


@dataclass
class Api:
    """A test client for the identity routes plus the world behind it."""

    client: AsyncClient
    world: World
    holder: dict[str, Actor | None] = field(default_factory=dict)

    def login_as(
        self,
        user: User,
        *,
        session: LoginSession | None = None,
        **fields: Any,
    ) -> Actor:
        """Authenticate the next requests as this user."""
        actor = Actor(
            user_id=user.id,
            roles=frozenset(user.roles),
            session_id=session.id if session else None,
            **fields,
        )
        self.holder["actor"] = actor
        return actor

    async def admin(self) -> Actor:
        """Create an Administration user and authenticate as them."""
        admin = await self.world.add_user(
            roles={Role.ADMIN},
            otp_enabled=True,
            login="root.admin",
            recovery_email="root@example.org",
        )
        return self.login_as(admin)


@pytest.fixture
async def api(auth_world: World, http_client: HttpClientFactory) -> Api:
    """The identity routers over the in-memory world."""
    holder: dict[str, Actor | None] = {"actor": None}

    def current_actor() -> Actor:
        actor = holder["actor"]
        if actor is None:
            raise UnauthorizedError(support_details="no test actor")
        return actor

    identity = SimpleNamespace(auth=auth_world.auth, token_verifier=None)
    client = await http_client(
        [*OAUTH_ROUTERS, *ID_ROUTERS, *ADMIN_ROUTERS],
        {get_actor: current_actor},
        identity=identity,
    )
    return Api(client=client, world=auth_world, holder=holder)

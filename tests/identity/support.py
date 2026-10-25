"""Builders and helpers shared by the identity tests."""

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from app.modules.identity.domain.connector import McpConnector
from app.modules.identity.domain.session import SESSION_LIFETIME, LoginSession
from app.modules.identity.domain.telegram_link import TelegramLink
from app.modules.identity.domain.user import User
from app.modules.identity.wiring_auth import AuthServices
from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock
from tests.fakes.files.services import FilesFakes
from tests.fakes.identity.hydra import FakeHydra
from tests.fakes.identity.senders import (
    FakeEmailSender,
    FakeOtpSender,
    FakeTelegramSender,
)
from tests.fakes.identity.uow import FakeIdentityUnitOfWork, IdentityStore

PASSWORD = "Str0ngPass"
BOT_TOKEN = "000:dev"


@dataclass
class World:
    """Everything a unit test needs: use cases over in-memory fakes."""

    auth: AuthServices
    store: IdentityStore
    hydra: FakeHydra
    otp: FakeOtpSender
    email: FakeEmailSender
    clock: FixedClock
    redis: Any
    kicker: Any
    telegram: FakeTelegramSender
    files: FilesFakes
    webauthn: Any = None

    def uow(self) -> FakeIdentityUnitOfWork:
        """A unit of work over the same store."""
        return FakeIdentityUnitOfWork(self.store, self.clock)

    async def add_user(self, **fields: Any) -> User:
        """Insert an active user with a known password (PASSWORD)."""
        user = make_user(**fields)
        if "password_hash" not in fields:
            user.password_hash = await self.auth.hasher.hash(PASSWORD)
        self.store.users[user.id] = user
        return user

    def add_session(self, user: User, **fields: Any) -> LoginSession:
        """Insert an active session of the user."""
        now = self.clock.now()
        session = LoginSession(
            id=fields.pop("id", new_id()),
            user_id=user.id,
            ip=fields.pop("ip", "203.0.113.5"),
            user_agent=fields.pop("user_agent", "pytest"),
            expires_at=fields.pop("expires_at", now + SESSION_LIFETIME),
            last_seen_at=fields.pop("last_seen_at", now),
            amr=fields.pop("amr", ["pwd"]),
            **fields,
        )
        self.store.sessions[session.id] = session
        return session

    def add_link(
        self, user: User, telegram_user_id: int = 555, **fields: Any
    ) -> TelegramLink:
        """Insert a Telegram link."""
        link = TelegramLink(
            telegram_user_id=telegram_user_id,
            user_id=user.id,
            first_name=fields.pop("first_name", "Tg"),
            linked_at=self.clock.now(),
            last_seen_at=self.clock.now(),
            **fields,
        )
        self.store.links[telegram_user_id] = link
        return link

    def add_connector(self, user: User, **fields: Any) -> McpConnector:
        """Insert a connector."""
        connector = McpConnector(
            id=fields.pop("id", new_id()),
            user_id=user.id,
            name=fields.pop("name", "Claude"),
            server=fields.pop("server", "student"),
            scopes=fields.pop("scopes", ["schedule:read"]),
            **fields,
        )
        self.store.connectors[connector.id] = connector
        return connector

    def user(self, user_id: UUID) -> User:
        """The stored user."""
        return self.store.users[user_id]


def make_user(**fields: Any) -> User:
    """An active student unless told otherwise."""
    uid = fields.pop("id", new_id())
    first = fields.pop("first_name", "Aleksey")
    last = fields.pop("last_name", "Brastilov")
    defaults: dict[str, Any] = {
        "login": f"{last.lower()}.{first.lower()}",
        "roles": {Role.STUDENT},
        "status": UserStatus.ACTIVE,
        "recovery_email": f"{first.lower()}@example.org",
        "recovery_email_verified_at": datetime(2026, 1, 1).astimezone(),
        "created_at": datetime(2026, 1, 1).astimezone(),
    }
    defaults.update(fields)
    return User(id=uid, first_name=first, last_name=last, **defaults)


def sign_init_data(
    *,
    telegram_id: int = 555,
    username: str | None = "aleksey",
    auth_date: int,
    bot_token: str = BOT_TOKEN,
    extra: dict[str, str] | None = None,
) -> str:
    """Telegram-style initData signed with the bot token (HMAC method)."""
    user = {"id": telegram_id, "first_name": "Aleksey", "language_code": "ru"}
    if username:
        user["username"] = username
    fields = {
        "query_id": "AAH-test",
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(auth_date),
        "signature": "sig-for-tests",
        **(extra or {}),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": digest})

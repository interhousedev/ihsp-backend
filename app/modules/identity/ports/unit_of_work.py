"""Port: the identity unit of work."""

from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Protocol, Self

from app.modules.identity.ports.audit_event_repository import AuditEventRepository
from app.modules.identity.ports.connector_repository import ConnectorRepository
from app.modules.identity.ports.factor_repository import FactorRepository
from app.modules.identity.ports.session_repository import SessionRepository
from app.modules.identity.ports.telegram_link_repository import (
    TelegramLinkRepository,
)
from app.modules.identity.ports.user_repository import UserRepository
from app.shared.notifications import AuditDraft, NotificationDraft


class IdentityUnitOfWorkPort(Protocol):
    """One transaction with identity repositories, outbox and audit."""

    @property
    def users(self) -> UserRepository:
        """User repository."""
        ...

    @property
    def sessions(self) -> SessionRepository:
        """Session repository."""
        ...

    @property
    def telegram_links(self) -> TelegramLinkRepository:
        """Telegram link repository."""
        ...

    @property
    def connectors(self) -> ConnectorRepository:
        """Connector repository."""
        ...

    @property
    def factors(self) -> FactorRepository:
        """TOTP state and passkeys."""
        ...

    @property
    def audit_events(self) -> AuditEventRepository:
        """Audit event reader."""
        ...

    async def __aenter__(self) -> Self:
        """Open the transaction."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Roll back unless committed."""
        ...

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications for the outbox."""
        ...

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events."""
        ...

    def after_commit(self, hook: Callable[[], Awaitable[None]]) -> None:
        """Run a coroutine after a successful commit."""
        ...

    async def commit(self) -> None:
        """Commit the transaction."""
        ...


UowFactory = Callable[[], IdentityUnitOfWorkPort]

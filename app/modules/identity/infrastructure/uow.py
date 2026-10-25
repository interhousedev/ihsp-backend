"""Unit of work of the identity module."""

from app.modules.identity.infrastructure.repositories.audit_event_repository import (
    SqlAuditEventRepository,
)
from app.modules.identity.infrastructure.repositories.connector_repository import (
    SqlConnectorRepository,
)
from app.modules.identity.infrastructure.repositories.factor_repository import (
    SqlFactorRepository,
)
from app.modules.identity.infrastructure.repositories.session_repository import (
    SqlSessionRepository,
)
from app.modules.identity.infrastructure.repositories.telegram_link_repository import (
    SqlTelegramLinkRepository,
)
from app.modules.identity.infrastructure.repositories.user_repository import (
    SqlUserRepository,
)
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.db.uow import SqlUnitOfWork
from app.shared.wiring import ModuleDeps


class IdentityUnitOfWork(SqlUnitOfWork):
    """One transaction with the identity repositories."""

    users: SqlUserRepository
    sessions: SqlSessionRepository
    telegram_links: SqlTelegramLinkRepository
    connectors: SqlConnectorRepository
    audit_events: SqlAuditEventRepository
    factors: SqlFactorRepository

    def _init_repos(self) -> None:
        """Create the repositories on the fresh session."""
        self.users = SqlUserRepository(self.session)
        self.sessions = SqlSessionRepository(self.session)
        self.telegram_links = SqlTelegramLinkRepository(self.session)
        self.connectors = SqlConnectorRepository(self.session)
        self.audit_events = SqlAuditEventRepository(self.session)
        self.factors = SqlFactorRepository(self.session)


def make_uow_factory(deps: ModuleDeps) -> UowFactory:
    """Return a factory that builds a fresh unit of work per use case call."""

    def factory() -> IdentityUnitOfWork:
        return IdentityUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    return factory

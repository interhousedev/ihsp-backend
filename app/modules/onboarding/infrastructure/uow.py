"""SQL unit of work of the onboarding module."""

from app.modules.onboarding.infrastructure.repositories.sql import (
    SqlProgressRepository,
)
from app.shared.db.uow import SqlUnitOfWork


class SqlOnboardingUnitOfWork(SqlUnitOfWork):
    """One transaction over progress rows."""

    progress: SqlProgressRepository

    def _init_repos(self) -> None:
        """Create the repository on the open session."""
        self.progress = SqlProgressRepository(self.session)

"""SQL unit of work of the feedback module."""

from app.modules.feedback.infrastructure.repositories.feedback_repository import (
    SqlFeedbackRepository,
)
from app.shared.db.uow import SqlUnitOfWork


class SqlFeedbackUnitOfWork(SqlUnitOfWork):
    """One transaction over feedback items and responses."""

    feedback: SqlFeedbackRepository

    def _init_repos(self) -> None:
        """Create the repository on the open session."""
        self.feedback = SqlFeedbackRepository(self.session)

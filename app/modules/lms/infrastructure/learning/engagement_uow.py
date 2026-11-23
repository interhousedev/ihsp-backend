"""Unit of work of the engagement use cases: learning repositories plus XP."""

from app.modules.lms.infrastructure.learning.repositories.engagement_repository import (
    SqlEngagementRepository,
)
from app.modules.lms.infrastructure.learning.uow import SqlLearningUnitOfWork


class SqlEngagementUnitOfWork(SqlLearningUnitOfWork):
    """The learning transaction with the engagement repository."""

    engagement: SqlEngagementRepository

    def _init_repos(self) -> None:
        """Create the learning repositories and the engagement one."""
        super()._init_repos()
        self.engagement = SqlEngagementRepository(self.session)

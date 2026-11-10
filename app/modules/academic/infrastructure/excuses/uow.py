"""The excuse unit of work over one SQLAlchemy session."""

from app.modules.academic.infrastructure.classwork.work_off_repository import (
    SqlWorkOffRepository,
)
from app.modules.academic.infrastructure.excuses.repository import SqlExcuseRepository
from app.shared.db.uow import SqlUnitOfWork


class SqlExcuseUnitOfWork(SqlUnitOfWork):
    """One transaction with the excuse and work-off repositories bound to it."""

    excuses: SqlExcuseRepository
    work_offs: SqlWorkOffRepository

    def _init_repos(self) -> None:
        """Create the repositories bound to the open session."""
        self.excuses = SqlExcuseRepository(self.session)
        self.work_offs = SqlWorkOffRepository(self.session)

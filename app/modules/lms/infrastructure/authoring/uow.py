"""Unit of work of course authoring."""

from app.modules.lms.infrastructure.authoring.attempt_reader import SqlAttemptReader
from app.modules.lms.infrastructure.authoring.course_repository import (
    SqlCourseRepository,
)
from app.modules.lms.infrastructure.authoring.revision_repository import (
    SqlRevisionRepository,
)
from app.modules.lms.infrastructure.authoring.staff_repository import SqlStaffRepository
from app.modules.lms.infrastructure.authoring.step_repository import SqlStepRepository
from app.modules.lms.infrastructure.authoring.version_repository import (
    SqlVersionRepository,
)
from app.shared.db.uow import SqlUnitOfWork


class SqlAuthoringUnitOfWork(SqlUnitOfWork):
    """One transaction over the authoring tables."""

    courses: SqlCourseRepository
    staff: SqlStaffRepository
    steps: SqlStepRepository
    revisions: SqlRevisionRepository
    versions: SqlVersionRepository
    attempts: SqlAttemptReader

    def _init_repos(self) -> None:
        """Create repositories bound to the open session."""
        self.courses = SqlCourseRepository(self.session)
        self.staff = SqlStaffRepository(self.session)
        self.steps = SqlStepRepository(self.session)
        self.revisions = SqlRevisionRepository(self.session)
        self.versions = SqlVersionRepository(self.session)
        self.attempts = SqlAttemptReader(self.session)

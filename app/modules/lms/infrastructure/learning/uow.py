"""Unit of work of the learning side."""

from app.modules.lms.infrastructure.learning.repositories.attempt_repository import (
    SqlAttemptRepository,
)
from app.modules.lms.infrastructure.learning.repositories.course_repository import (
    SqlCourseRepository,
)
from app.modules.lms.infrastructure.learning.repositories.enrollment_repository import (
    SqlEnrollmentRepository,
)
from app.modules.lms.infrastructure.learning.repositories.revision_repository import (
    SqlRevisionRepository,
)
from app.modules.lms.infrastructure.learning.repositories.staff_repository import (
    SqlStaffRepository,
)
from app.modules.lms.infrastructure.learning.repositories.step_repository import (
    SqlStepRepository,
)
from app.modules.lms.infrastructure.learning.repositories.step_state_repository import (
    SqlStepStateRepository,
)
from app.modules.lms.infrastructure.learning.repositories.version_repository import (
    SqlVersionRepository,
)
from app.shared.db.uow import SqlUnitOfWork


class SqlLearningUnitOfWork(SqlUnitOfWork):
    """One transaction over the learning repositories."""

    courses: SqlCourseRepository
    versions: SqlVersionRepository
    staff: SqlStaffRepository
    steps: SqlStepRepository
    revisions: SqlRevisionRepository
    enrollments: SqlEnrollmentRepository
    states: SqlStepStateRepository
    attempts: SqlAttemptRepository

    def _init_repos(self) -> None:
        """Create the repositories bound to the session."""
        self.courses = SqlCourseRepository(self.session)
        self.versions = SqlVersionRepository(self.session)
        self.staff = SqlStaffRepository(self.session)
        self.steps = SqlStepRepository(self.session)
        self.revisions = SqlRevisionRepository(self.session)
        self.enrollments = SqlEnrollmentRepository(self.session)
        self.states = SqlStepStateRepository(self.session)
        self.attempts = SqlAttemptRepository(self.session)

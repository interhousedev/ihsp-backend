"""Port: the unit of work of the learning side."""

from types import TracebackType
from typing import Protocol, Self

from app.modules.lms.ports.learning.attempt_repository import AttemptRepository
from app.modules.lms.ports.learning.course_repository import CourseRepository
from app.modules.lms.ports.learning.enrollment_repository import EnrollmentRepository
from app.modules.lms.ports.learning.revision_repository import RevisionRepository
from app.modules.lms.ports.learning.staff_repository import StaffRepository
from app.modules.lms.ports.learning.step_repository import StepRepository
from app.modules.lms.ports.learning.step_state_repository import StepStateRepository
from app.modules.lms.ports.learning.version_repository import VersionRepository


class LearningUnitOfWork(Protocol):
    """One transaction over the learning repositories."""

    @property
    def courses(self) -> CourseRepository:
        """Courses with their live values."""
        ...

    @property
    def versions(self) -> VersionRepository:
        """Published versions."""
        ...

    @property
    def staff(self) -> StaffRepository:
        """Course staff."""
        ...

    @property
    def steps(self) -> StepRepository:
        """Steps."""
        ...

    @property
    def revisions(self) -> RevisionRepository:
        """Step revisions."""
        ...

    @property
    def enrollments(self) -> EnrollmentRepository:
        """Enrollments."""
        ...

    @property
    def states(self) -> StepStateRepository:
        """Step states."""
        ...

    @property
    def attempts(self) -> AttemptRepository:
        """Test attempts."""
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
        """Roll back unless committed, then close."""
        ...

    async def commit(self) -> None:
        """Commit the transaction."""
        ...

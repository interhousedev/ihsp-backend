"""Port: the unit of work of course authoring."""

from types import TracebackType
from typing import Protocol, Self

from app.modules.lms.ports.authoring.attempt_reader import AttemptReader
from app.modules.lms.ports.authoring.course_repository import CourseRepository
from app.modules.lms.ports.authoring.revision_repository import RevisionRepository
from app.modules.lms.ports.authoring.staff_repository import StaffRepository
from app.modules.lms.ports.authoring.step_repository import StepRepository
from app.modules.lms.ports.authoring.version_repository import VersionRepository


class AuthoringUnitOfWork(Protocol):
    """One transaction over the authoring repositories."""

    @property
    def courses(self) -> CourseRepository:
        """Courses and their draft working copy."""
        ...

    @property
    def staff(self) -> StaffRepository:
        """Course staff."""
        ...

    @property
    def steps(self) -> StepRepository:
        """Course steps."""
        ...

    @property
    def revisions(self) -> RevisionRepository:
        """Immutable step revisions."""
        ...

    @property
    def versions(self) -> VersionRepository:
        """Course versions."""
        ...

    @property
    def attempts(self) -> AttemptReader:
        """Read-only access to test attempts."""
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

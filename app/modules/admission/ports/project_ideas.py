"""Ports of the project-ideas slice: runs per student and curated helpers."""

from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.project_ideas import Helper, ProjectRun


class ProjectRunRepository(Protocol):
    """Generations of project ideas, newest first, a few kept per student."""

    async def add(self, run: ProjectRun, *, keep: int) -> None:
        """Store a run and drop the student's runs beyond the `keep` newest."""
        ...

    async def latest(self, student_id: UUID) -> ProjectRun | None:
        """The newest run of the student."""
        ...

    async def history(self, student_id: UUID, *, limit: int) -> list[ProjectRun]:
        """The newest runs of the student, newest first."""
        ...

    async def get(self, student_id: UUID, run_id: UUID) -> ProjectRun | None:
        """One run of the student, else None."""
        ...


class HelperRepository(Protocol):
    """Curated helpers and organizations."""

    async def list(self, *, active_only: bool) -> list[Helper]:
        """Helpers ordered by name."""
        ...

    async def get(self, helper_id: UUID) -> Helper | None:
        """One helper, else None."""
        ...

    async def save(self, helper: Helper) -> Helper:
        """Insert or overwrite a helper."""
        ...

    async def delete(self, helper_id: UUID) -> bool:
        """Delete a helper; return whether it existed."""
        ...

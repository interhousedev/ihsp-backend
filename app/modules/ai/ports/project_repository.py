"""Port: projects and the files attached to them."""

from typing import Protocol
from uuid import UUID

from app.modules.ai.domain.project import Project


class ProjectRepository(Protocol):
    """Projects of the students and their files (file ids; the files are elsewhere)."""

    async def add(self, project: Project) -> None:
        """Insert a new project."""
        ...

    async def get(self, project_id: UUID) -> Project | None:
        """Return the project or None."""
        ...

    async def save(self, project: Project) -> None:
        """Write the project's name and instructions."""
        ...

    async def delete(self, project_id: UUID) -> None:
        """Delete the project; its files are unlinked, its chats stay (no project)."""
        ...

    async def list_for_owner(self, owner_id: UUID) -> list[Project]:
        """Return the owner's projects, newest first."""
        ...

    async def add_file(self, project_id: UUID, file_id: UUID) -> None:
        """Attach a file to the project (attaching twice is a no-op)."""
        ...

    async def remove_file(self, project_id: UUID, file_id: UUID) -> None:
        """Detach a file from the project."""
        ...

    async def file_ids(self, project_id: UUID) -> list[UUID]:
        """Return the attached file ids, oldest first."""
        ...

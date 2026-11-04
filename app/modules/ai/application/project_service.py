"""Use cases: a student's projects, their files and the chats inside them.

Projects are owner-only: another student's project looks missing (404), so ids
cannot be probed. A file joins a project only when the student owns it and its text
is ready; the project's chats search those files and no others.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.ai.domain.errors import AttachmentInvalidError, ProjectNotFoundError
from app.modules.ai.domain.project import Project
from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi
from app.shared.ids import new_id


@dataclass(frozen=True, slots=True)
class ProjectView:
    """A project as the API shows it."""

    id: UUID
    name: str
    instructions: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ProjectFileView:
    """A file attached to a project."""

    file_id: UUID
    name: str
    status: str


def project_view(project: Project) -> ProjectView:
    """The API view of a project."""
    return ProjectView(
        id=project.id,
        name=project.name,
        instructions=project.instructions,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


class ProjectService:
    """Create, read, change and delete projects; attach and list their files."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AiUnitOfWork],
        files: FilesApi,
        clock: Clock,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.files = files
        self.clock = clock

    async def mine(self, actor: Actor) -> list[ProjectView]:
        """The caller's projects, newest first."""
        async with self.uow_factory() as uow:
            projects = await uow.projects.list_for_owner(actor.user_id)
        return [project_view(p) for p in projects]

    async def create(
        self, actor: Actor, *, name: str, instructions: str
    ) -> ProjectView:
        """Start a project."""
        now = self.clock.now()
        project = Project(
            id=new_id(),
            owner_id=actor.user_id,
            name=name.strip(),
            instructions=instructions,
            created_at=now,
            updated_at=now,
        )
        async with self.uow_factory() as uow:
            await uow.projects.add(project)
            await uow.commit()
        return project_view(project)

    async def get(self, actor: Actor, project_id: UUID) -> ProjectView:
        """One of the caller's projects."""
        async with self.uow_factory() as uow:
            project = await self._owned(uow, actor, project_id)
        return project_view(project)

    async def update(
        self,
        actor: Actor,
        project_id: UUID,
        *,
        name: str | None = None,
        instructions: str | None = None,
    ) -> ProjectView:
        """Change the name and/or the instructions."""
        async with self.uow_factory() as uow:
            project = await self._owned(uow, actor, project_id)
            if name is not None:
                project.name = name.strip()
            if instructions is not None:
                project.instructions = instructions
            project.updated_at = self.clock.now()
            await uow.projects.save(project)
            await uow.commit()
        return project_view(project)

    async def delete(self, actor: Actor, project_id: UUID) -> None:
        """Delete the project; its chats remain, outside any project."""
        async with self.uow_factory() as uow:
            await self._owned(uow, actor, project_id)
            await uow.projects.delete(project_id)
            await uow.commit()

    async def files_of(self, actor: Actor, project_id: UUID) -> list[ProjectFileView]:
        """The files of the project that still exist, in the order they were added."""
        async with self.uow_factory() as uow:
            await self._owned(uow, actor, project_id)
            ids = await uow.projects.file_ids(project_id)
        refs = await self.files.get_many(ids)
        return [
            ProjectFileView(file_id=ref.id, name=ref.name, status=ref.status)
            for file_id in ids
            if (ref := refs.get(file_id)) is not None
        ]

    async def attach_file(self, actor: Actor, project_id: UUID, file_id: UUID) -> None:
        """Attach one of the caller's own files whose text is ready.

        Raises:
            AttachmentInvalidError: Not the caller's file, missing or not ready.
        """
        async with self.uow_factory() as uow:
            await self._owned(uow, actor, project_id)
        ref = await self.files.get(file_id)
        if ref is None or ref.owner_id != actor.user_id or ref.status != "ready":
            raise AttachmentInvalidError(params={"file_id": str(file_id)})
        async with self.uow_factory() as uow:
            await self._owned(uow, actor, project_id)
            await uow.projects.add_file(project_id, file_id)
            await uow.commit()

    async def detach_file(self, actor: Actor, project_id: UUID, file_id: UUID) -> None:
        """Remove a file from the project (the file itself stays)."""
        async with self.uow_factory() as uow:
            await self._owned(uow, actor, project_id)
            await uow.projects.remove_file(project_id, file_id)
            await uow.commit()

    async def _owned(
        self, uow: AiUnitOfWork, actor: Actor, project_id: UUID
    ) -> Project:
        project = await uow.projects.get(project_id)
        if project is None or project.owner_id != actor.user_id:
            raise ProjectNotFoundError(params={"project_id": str(project_id)})
        return project

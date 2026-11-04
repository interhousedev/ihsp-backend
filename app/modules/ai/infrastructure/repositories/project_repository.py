"""SQL repository of projects and their files (ai.projects, ai.project_files)."""

from uuid import UUID

from app.modules.ai.domain.project import Project
from app.modules.ai.infrastructure.orm.chat import Chat as ChatRow
from app.modules.ai.infrastructure.orm.project import Project as ProjectRow
from app.modules.ai.infrastructure.orm.project import ProjectFile

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


def _to_entity(row: ProjectRow) -> Project:
    return Project(
        id=row.id,
        owner_id=row.owner_id,
        name=row.name,
        instructions=row.instructions or "",
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlProjectRepository:
    """Projects in `ai.projects` and their files in `ai.project_files`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def add(self, project: Project) -> None:
        """Insert a new project."""
        self.session.add(
            ProjectRow(
                id=project.id,
                owner_id=project.owner_id,
                name=project.name,
                instructions=project.instructions,
            )
        )
        await self.session.flush()

    async def get(self, project_id: UUID) -> Project | None:
        """Return the project or None."""
        row = await self.session.get(ProjectRow, project_id)
        return _to_entity(row) if row else None

    async def save(self, project: Project) -> None:
        """Write the project's name and instructions."""
        await self.session.execute(
            update(ProjectRow)
            .where(ProjectRow.id == project.id)
            .values(
                name=project.name,
                instructions=project.instructions,
                updated_at=project.updated_at,
            )
        )

    async def delete(self, project_id: UUID) -> None:
        """Delete the project; its files go with it, its chats lose the link."""
        await self.session.execute(
            update(ChatRow)
            .where(ChatRow.project_id == project_id)
            .values(project_id=None)
        )
        await self.session.execute(
            delete(ProjectRow).where(ProjectRow.id == project_id)
        )

    async def list_for_owner(self, owner_id: UUID) -> list[Project]:
        """Return the owner's projects, newest first."""
        rows = await self.session.scalars(
            select(ProjectRow)
            .where(ProjectRow.owner_id == owner_id)
            .order_by(ProjectRow.created_at.desc(), ProjectRow.id.desc())
        )
        return [_to_entity(row) for row in rows]

    async def add_file(self, project_id: UUID, file_id: UUID) -> None:
        """Attach a file to the project (attaching twice is a no-op)."""
        await self.session.execute(
            insert(ProjectFile)
            .values(project_id=project_id, file_id=file_id)
            .on_conflict_do_nothing(index_elements=["project_id", "file_id"])
        )

    async def remove_file(self, project_id: UUID, file_id: UUID) -> None:
        """Detach a file from the project."""
        await self.session.execute(
            delete(ProjectFile).where(
                ProjectFile.project_id == project_id, ProjectFile.file_id == file_id
            )
        )

    async def file_ids(self, project_id: UUID) -> list[UUID]:
        """Return the attached file ids, oldest first."""
        rows = await self.session.scalars(
            select(ProjectFile.file_id)
            .where(ProjectFile.project_id == project_id)
            .order_by(ProjectFile.created_at, ProjectFile.file_id)
        )
        return list(rows)

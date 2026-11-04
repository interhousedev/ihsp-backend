"""Routes of the student's projects (`/v1/ai/projects`): owner-only."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.ai.schemas import (
    AttachFileBody,
    ProjectBody,
    ProjectFileResponse,
    ProjectPatchBody,
    ProjectResponse,
)
from app.shared.actor import Actor

from fastapi import Depends


async def list_projects(
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> list[ProjectResponse]:
    """The caller's projects, newest first."""
    views = await container.ai.projects.mine(actor)
    return [ProjectResponse.from_view(v) for v in views]


async def create_project(
    body: ProjectBody,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> ProjectResponse:
    """Start a project."""
    view = await container.ai.projects.create(
        actor, name=body.name, instructions=body.instructions
    )
    return ProjectResponse.from_view(view)


async def get_project(
    project_id: UUID,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> ProjectResponse:
    """One of the caller's projects (another student's looks missing)."""
    view = await container.ai.projects.get(actor, project_id)
    return ProjectResponse.from_view(view)


async def patch_project(
    project_id: UUID,
    body: ProjectPatchBody,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> ProjectResponse:
    """Change the name and/or the instructions."""
    view = await container.ai.projects.update(
        actor, project_id, name=body.name, instructions=body.instructions
    )
    return ProjectResponse.from_view(view)


async def delete_project(
    project_id: UUID,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> None:
    """Delete the project; its chats stay, outside any project."""
    await container.ai.projects.delete(actor, project_id)


async def list_project_files(
    project_id: UUID,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> list[ProjectFileResponse]:
    """The files attached to the project."""
    views = await container.ai.projects.files_of(actor, project_id)
    return [
        ProjectFileResponse(file_id=v.file_id, name=v.name, status=v.status)
        for v in views
    ]


async def attach_project_file(
    project_id: UUID,
    body: AttachFileBody,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> None:
    """Attach one of the caller's own ready files to the project."""
    await container.ai.projects.attach_file(actor, project_id, body.file_id)


async def detach_project_file(
    project_id: UUID,
    file_id: UUID,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> None:
    """Remove a file from the project (the file stays)."""
    await container.ai.projects.detach_file(actor, project_id, file_id)

"""DELETE /v1/certificates/me/{entry_id}/files/{file_id}."""

from uuid import UUID

from app.interfaces.http.v1.certificates.deps import ContainerDep, StudentActor

from fastapi import Response, status


async def remove_entry_file(
    entry_id: UUID, file_id: UUID, container: ContainerDep, actor: StudentActor
) -> Response:
    """Delete one file of the caller's entry."""
    await container.certificates.remove_entry_file.execute(
        actor.user_id, entry_id, file_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

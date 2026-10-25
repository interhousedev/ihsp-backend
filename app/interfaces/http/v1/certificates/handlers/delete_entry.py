"""DELETE /v1/certificates/me/{entry_id}."""

from uuid import UUID

from app.interfaces.http.v1.certificates.deps import ContainerDep, StudentActor

from fastapi import Response, status


async def delete_entry(
    entry_id: UUID, container: ContainerDep, actor: StudentActor
) -> Response:
    """Delete the caller's certificate with its files."""
    await container.certificates.delete_entry.execute(actor.user_id, entry_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

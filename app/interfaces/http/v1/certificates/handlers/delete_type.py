"""DELETE /v1/certificates/admin/types/{type_id}."""

from uuid import UUID

from app.interfaces.http.v1.certificates.deps import AdminActor, ContainerDep

from fastapi import Response, status


async def delete_type(
    type_id: UUID, container: ContainerDep, actor: AdminActor
) -> Response:
    """Delete a custom type nobody uses."""
    await container.certificates.delete_type.execute(type_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

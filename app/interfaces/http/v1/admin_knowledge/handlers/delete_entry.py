"""DELETE /v1/admin/knowledge/{entry_id}."""

from uuid import UUID

from app.interfaces.http.v1.admin_knowledge.deps import AdminActor, ContainerDep

from fastapi import Response, status


async def delete_entry(
    entry_id: UUID, container: ContainerDep, actor: AdminActor
) -> Response:
    """Delete an entry."""
    await container.knowledge.delete_entry.execute(entry_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

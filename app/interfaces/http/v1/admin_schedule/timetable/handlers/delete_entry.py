"""DELETE /v1/admin/timetable/{id}."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep

from fastapi import Response


async def delete_entry(
    entry_id: UUID, container: ContainerDep, actor: AdminActor
) -> Response:
    """Delete an entry and tidy its future lessons."""
    await container.academic.schedule.delete_entry.execute(entry_id)
    return Response(status_code=204)

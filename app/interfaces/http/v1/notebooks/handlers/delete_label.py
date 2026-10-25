"""DELETE /v1/notebooks/{id}/labels/{label_id}."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks

from fastapi import Response, status


async def delete_label(
    notebook_id: UUID, label_id: UUID, notebooks: Notebooks, actor: MemberActor
) -> Response:
    """Delete a label; the sources that carried it lose it."""
    await notebooks.delete_label.execute(actor, notebook_id, label_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

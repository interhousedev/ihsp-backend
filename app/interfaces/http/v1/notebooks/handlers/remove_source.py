"""DELETE /v1/notebooks/{id}/sources/{sid}."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks

from fastapi import Response, status


async def remove_source(
    notebook_id: UUID, source_id: UUID, notebooks: Notebooks, actor: MemberActor
) -> Response:
    """Remove a source and its passages from the notebook."""
    await notebooks.remove_source.execute(actor, notebook_id, source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

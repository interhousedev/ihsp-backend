"""DELETE /v1/notebooks/{id}."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks

from fastapi import Response, status


async def delete_notebook(
    notebook_id: UUID, notebooks: Notebooks, actor: MemberActor
) -> Response:
    """Delete a notebook with its sources, chat and outputs."""
    await notebooks.delete_notebook.execute(actor, notebook_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

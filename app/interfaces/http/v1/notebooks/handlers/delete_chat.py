"""DELETE /v1/notebooks/{id}/chat."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks

from fastapi import Response, status


async def delete_chat(
    notebook_id: UUID, actor: MemberActor, notebooks: Notebooks
) -> Response:
    """Delete the student's thread in the notebook."""
    await notebooks.delete_chat.execute(actor, notebook_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

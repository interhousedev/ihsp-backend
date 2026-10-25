"""DELETE /v1/me/flashcard-sets/{id}."""

from uuid import UUID

from app.interfaces.http.v1.flashcards.deps import ContainerDep, OwnerActor

from fastapi import Response, status


async def delete_set(
    set_id: UUID, container: ContainerDep, actor: OwnerActor
) -> Response:
    """Delete one of the caller's sets with its cards."""
    await container.flashcards.delete_set.execute(owner_id=actor.user_id, set_id=set_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""GET /v1/me/flashcard-sets/{id}."""

from uuid import UUID

from app.interfaces.http.v1.flashcards.deps import ContainerDep, OwnerActor
from app.interfaces.http.v1.flashcards.schemas import SetDetailResponse


async def get_set(
    set_id: UUID, container: ContainerDep, actor: OwnerActor
) -> SetDetailResponse:
    """Open one of the caller's sets with its cards."""
    view = await container.flashcards.get_set.execute(
        owner_id=actor.user_id, set_id=set_id
    )
    return SetDetailResponse.from_detail(view)

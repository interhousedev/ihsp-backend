"""GET /v1/me/flashcard-sets/{id}/study."""

from uuid import UUID

from app.interfaces.http.v1.flashcards.deps import ContainerDep, OwnerActor
from app.interfaces.http.v1.flashcards.schemas import StudyNextResponse


async def study_next(
    set_id: UUID, container: ContainerDep, actor: OwnerActor
) -> StudyNextResponse:
    """Return the next card to study in the set."""
    view = await container.flashcards.study_next.execute(
        owner_id=actor.user_id, set_id=set_id
    )
    return StudyNextResponse.from_view(view)

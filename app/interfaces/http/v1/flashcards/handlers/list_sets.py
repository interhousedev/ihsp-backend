"""GET /v1/me/flashcard-sets."""

from app.interfaces.http.v1.flashcards.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.flashcards.schemas import SetItemResponse


async def list_sets(
    container: ContainerDep, actor: StudentActor
) -> list[SetItemResponse]:
    """List the caller's sets with today's due and new counts."""
    items = await container.flashcards.list_sets.execute(owner_id=actor.user_id)
    return [SetItemResponse.from_view(item) for item in items]

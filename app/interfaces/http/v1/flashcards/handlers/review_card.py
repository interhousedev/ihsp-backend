"""POST /v1/me/flashcards/{card_id}/review."""

from uuid import UUID

from app.interfaces.http.v1.flashcards.deps import ContainerDep, OwnerActor
from app.interfaces.http.v1.flashcards.schemas import ReviewBody, StudyNextResponse
from app.shared.srs import Rating


async def review_card(
    card_id: UUID, body: ReviewBody, container: ContainerDep, actor: OwnerActor
) -> StudyNextResponse:
    """Rate a card and return the next one."""
    view = await container.flashcards.review_card.execute(
        owner_id=actor.user_id,
        card_id=card_id,
        rating=Rating(body.rating),
        duration_ms=body.duration_ms,
    )
    return StudyNextResponse.from_view(view)

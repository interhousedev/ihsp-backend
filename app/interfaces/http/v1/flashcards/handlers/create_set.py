"""POST /v1/me/flashcard-sets."""

from app.interfaces.http.v1.flashcards.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.flashcards.schemas import CreateSetBody, SetDetailResponse
from app.modules.flashcards.domain.flashcard_set import SetSource


async def create_set(
    body: CreateSetBody, container: ContainerDep, actor: StudentActor
) -> SetDetailResponse:
    """Create a set by hand; its cards start as new."""
    view = await container.flashcards.create_set.execute(
        owner_id=actor.user_id,
        title=body.title,
        description=body.description,
        cards=[(card.front, card.back) for card in body.cards],
        source=SetSource.MANUAL,
    )
    return SetDetailResponse.from_detail(view)

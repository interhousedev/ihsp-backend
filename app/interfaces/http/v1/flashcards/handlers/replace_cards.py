"""PUT /v1/me/flashcard-sets/{id}/cards."""

from uuid import UUID

from app.interfaces.http.v1.flashcards.deps import ContainerDep, OwnerActor
from app.interfaces.http.v1.flashcards.schemas import (
    ReplaceCardsBody,
    SetDetailResponse,
)
from app.modules.flashcards.domain.flashcard import CardDraft


async def replace_cards(
    set_id: UUID, body: ReplaceCardsBody, container: ContainerDep, actor: OwnerActor
) -> SetDetailResponse:
    """Save the full ordered list of cards; ids that are missing are deleted."""
    view = await container.flashcards.replace_cards.execute(
        owner_id=actor.user_id,
        set_id=set_id,
        cards=[CardDraft(c.front, c.back, c.id) for c in body.cards],
    )
    return SetDetailResponse.from_detail(view)

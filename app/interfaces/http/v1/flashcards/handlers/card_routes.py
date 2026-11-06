"""Restart, merge, per-card statistics, and adding, editing, deleting cards."""

from uuid import UUID

from app.interfaces.http.v1.flashcards.deps import (
    ContainerDep,
    OwnerActor,
    StudentActor,
)
from app.interfaces.http.v1.flashcards.schemas import (
    AddCardsBody,
    CardResponse,
    CardStatsResponse,
    MergedSetResponse,
    MergeSetsBody,
    SetDetailResponse,
    StudyNextResponse,
    UpdateCardBody,
)
from app.modules.flashcards.domain.flashcard import Hardness


async def restart_study(
    set_id: UUID, container: ContainerDep, actor: OwnerActor
) -> StudyNextResponse:
    """Study every card again today; the schedule and limits stay untouched."""
    view = await container.flashcards.restart_study.execute(
        owner_id=actor.user_id, set_id=set_id
    )
    return StudyNextResponse.from_view(view)


async def merge_sets(
    body: MergeSetsBody, container: ContainerDep, actor: StudentActor
) -> MergedSetResponse:
    """Create a set from copies of the cards of several sets; the sources stay."""
    view = await container.flashcards.merge_sets.execute(
        owner_id=actor.user_id,
        set_ids=body.set_ids,
        title=body.title,
        description=body.description,
    )
    return MergedSetResponse.model_validate(view)


async def get_card_stats(
    set_id: UUID, container: ContainerDep, actor: OwnerActor
) -> list[CardStatsResponse]:
    """Return attempts, correct and incorrect answers and last study per card."""
    rows = await container.flashcards.get_card_stats.execute(
        owner_id=actor.user_id, set_id=set_id
    )
    return [CardStatsResponse.model_validate(row) for row in rows]


async def add_cards(
    set_id: UUID, body: AddCardsBody, container: ContainerDep, actor: OwnerActor
) -> SetDetailResponse:
    """Append a batch of new cards."""
    view = await container.flashcards.add_cards.execute(
        owner_id=actor.user_id,
        set_id=set_id,
        cards=[(c.front, c.back, c.hardness) for c in body.cards],
    )
    return SetDetailResponse.from_detail(view)


async def update_card(
    card_id: UUID, body: UpdateCardBody, container: ContainerDep, actor: OwnerActor
) -> CardResponse:
    """Change the text or the base hardness of one card."""
    view = await container.flashcards.update_card.execute(
        owner_id=actor.user_id,
        card_id=card_id,
        front=body.front,
        back=body.back,
        hardness=Hardness(body.hardness) if body.hardness else None,
    )
    return CardResponse.model_validate(view)


async def delete_card(
    card_id: UUID, container: ContainerDep, actor: OwnerActor
) -> None:
    """Delete one card."""
    await container.flashcards.delete_card.execute(
        owner_id=actor.user_id, card_id=card_id
    )

"""PATCH /v1/me/flashcard-sets/{id}."""

from uuid import UUID

from app.interfaces.http.v1.flashcards.deps import ContainerDep, OwnerActor
from app.interfaces.http.v1.flashcards.schemas import SetDetailResponse, UpdateSetBody
from app.modules.flashcards.application.update_set import UNSET


async def update_set(
    set_id: UUID, body: UpdateSetBody, container: ContainerDep, actor: OwnerActor
) -> SetDetailResponse:
    """Change the title, the description or the daily limits."""
    sent_description = "description" in body.model_fields_set
    view = await container.flashcards.update_set.execute(
        owner_id=actor.user_id,
        set_id=set_id,
        title=body.title,
        description=body.description if sent_description else UNSET,
        new_per_day=body.new_per_day,
        reviews_per_day=body.reviews_per_day,
    )
    return SetDetailResponse.from_detail(view)

"""POST /v1/me/flashcard-sets/copy."""

from app.interfaces.http.v1.flashcards.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.flashcards.schemas import CopyBody, SetDetailResponse


async def copy_from_share(
    body: CopyBody, container: ContainerDep, actor: StudentActor
) -> SetDetailResponse:
    """Copy a shared set to my sets with fresh progress."""
    view = await container.flashcards.copy_from_share.execute(
        actor=actor, share_slug=body.share_slug
    )
    return SetDetailResponse.from_detail(view)

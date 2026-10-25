"""GET /v1/lms/steps/{step_id}/cards/next: the next flash card of a block."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.lms_learning.cache import PRIVATE_NO_STORE
from app.modules.lms.application.learning.views import LearningCardStudyView
from app.shared.actor import Actor

from fastapi import Depends, Query, Response


async def next_card(
    step_id: UUID,
    block_id: Annotated[str, Query(min_length=1, max_length=64)],
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LearningCardStudyView:
    """Return the next card to study, with the button intervals and counts."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    view: LearningCardStudyView = await container.lms.learning.next_card.execute(
        actor, step_id, block_id
    )
    return view

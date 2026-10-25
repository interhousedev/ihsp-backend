"""POST /v1/lms/steps/{step_id}/cards/{card_id}/review: rate a flash card."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.lms_learning.cache import PRIVATE_NO_STORE
from app.interfaces.http.v1.lms_learning.schemas import LearningReviewCardBody
from app.modules.lms.application.learning.views import LearningCardStudyView
from app.shared.actor import Actor

from fastapi import Depends, Response


async def review_card(
    step_id: UUID,
    card_id: str,
    body: LearningReviewCardBody,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LearningCardStudyView:
    """Apply the rating and return the next card of the block."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    view: LearningCardStudyView = await container.lms.learning.review_card.execute(
        actor, step_id, card_id, body.rating
    )
    return view

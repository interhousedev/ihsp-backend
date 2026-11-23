"""The routes of graded code and HTML widgets of the learner player."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.lms_learning.cache import PRIVATE_NO_STORE
from app.interfaces.http.v1.lms_learning.schemas import LearningWidgetResultBody
from app.modules.lms.application.learning.views import (
    LearningBlockResultView,
    LearningHiddenTestsView,
)
from app.shared.actor import Actor

from fastapi import Depends, Response

# A widget reports once per run or submit; the bound stops a script from
# hammering the route (the result is self-reported and stored unverified).
WIDGET_RESULT_LIMIT = 20
WIDGET_RESULT_WINDOW_SECONDS = 60


async def record_widget_result(
    course_id: UUID,
    step_id: UUID,
    block_id: str,
    body: LearningWidgetResultBody,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LearningBlockResultView:
    """Store my score of a graded widget; the best score and a pass are kept."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    await container.rate_limiter.hit(
        f"lms:widget-result:{actor.user_id}",
        limit=WIDGET_RESULT_LIMIT,
        window_seconds=WIDGET_RESULT_WINDOW_SECONDS,
    )
    learning = container.lms.learning
    view: LearningBlockResultView = await learning.record_widget_result.execute(
        actor, course_id, step_id, block_id, body.score_pct, body.passed
    )
    return view


# The hidden tests are fetched once per submit; a generous bound still stops scraping.
HIDDEN_TESTS_LIMIT = 30
HIDDEN_TESTS_WINDOW_SECONDS = 60


async def get_hidden_tests(
    course_id: UUID,
    step_id: UUID,
    block_id: str,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LearningHiddenTestsView:
    """Return the hidden tests of a graded code block to run them on submit."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    await container.rate_limiter.hit(
        f"lms:hidden-tests:{actor.user_id}",
        limit=HIDDEN_TESTS_LIMIT,
        window_seconds=HIDDEN_TESTS_WINDOW_SECONDS,
    )
    learning = container.lms.learning
    view: LearningHiddenTestsView = await learning.get_hidden_tests.execute(
        actor, course_id, step_id, block_id
    )
    return view

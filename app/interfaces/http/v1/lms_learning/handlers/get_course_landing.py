"""GET /v1/lms/courses/{slug}/landing: the course landing page."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.lms_learning.cache import PRIVATE_CACHE
from app.modules.lms.application.learning.views import LearningLandingView
from app.shared.actor import Actor

from fastapi import Depends, Query, Response


async def get_course_landing(
    slug: str,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
    preview: Annotated[bool, Query()] = False,
) -> LearningLandingView:
    """Describe the course; `?preview=1` shows drafts to people who can edit."""
    response.headers["Cache-Control"] = PRIVATE_CACHE
    view: LearningLandingView = await container.lms.learning.get_course_landing.execute(
        actor, slug, preview=preview
    )
    return view

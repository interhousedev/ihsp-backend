"""Routes of the guest side of the LMS: the catalogue, a course and a lesson.

No Authorization header is read. Only published, active, public courses answer; a
draft, an unpublished, archived, invite-only or group course is a 404. Nothing
personal (progress, attempts, answers, enrolment) is exposed or written.
"""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_client_ip, get_container
from app.modules.lms.application.learning.views import (
    LearningCourseCardView,
    LearningGuestCoursePageView,
    LearningLandingView,
    LearningStepView,
)

from fastapi import APIRouter, Depends, Query, Response

# Shared caches may keep a guest page briefly: it is the same for everyone.
PUBLIC_CACHE = "public, max-age=60"

# Guests are anonymous, so the routes are limited per client address.
GUEST_LIMIT = 120
GUEST_WINDOW_SECONDS = 60


async def limit_guest(
    container: Annotated[Container, Depends(get_container)],
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> None:
    """Count one guest request per client address; over the limit answers 429."""
    await container.rate_limiter.hit(
        f"lms:public:{ip or 'unknown'}",
        limit=GUEST_LIMIT,
        window_seconds=GUEST_WINDOW_SECONDS,
    )


router = APIRouter(
    prefix="/v1/lms/public", tags=["lms-public"], dependencies=[Depends(limit_guest)]
)


@router.get("/courses")
async def list_public_courses(
    response: Response,
    container: Annotated[Container, Depends(get_container)],
    query: Annotated[str | None, Query(max_length=100)] = None,
) -> list[LearningCourseCardView]:
    """List the courses a guest may read, optionally filtered by title."""
    response.headers["Cache-Control"] = PUBLIC_CACHE
    cards: list[LearningCourseCardView] = (
        await container.lms.learning.public_courses.catalog(query)
    )
    return cards


@router.get("/courses/{slug}")
async def get_public_course(
    slug: str,
    response: Response,
    container: Annotated[Container, Depends(get_container)],
) -> LearningGuestCoursePageView:
    """Show a public course: description, staff names and outline, no progress."""
    response.headers["Cache-Control"] = PUBLIC_CACHE
    page: LearningGuestCoursePageView = (
        await container.lms.learning.public_courses.page(slug)
    )
    return page


@router.get("/courses/{slug}/landing")
async def get_public_course_landing(
    slug: str,
    response: Response,
    container: Annotated[Container, Depends(get_container)],
) -> LearningLandingView:
    """Describe a public course (what it teaches, authors, syllabus)."""
    response.headers["Cache-Control"] = PUBLIC_CACHE
    view: LearningLandingView = (
        await container.lms.learning.get_course_landing.execute_public(slug)
    )
    return view


@router.get("/courses/{course_id}/steps/{step_id}")
async def get_public_step(
    course_id: UUID,
    step_id: UUID,
    response: Response,
    container: Annotated[Container, Depends(get_container)],
) -> LearningStepView:
    """Return a lesson of a public course without answers or personal state."""
    response.headers["Cache-Control"] = PUBLIC_CACHE
    view: LearningStepView = await container.lms.learning.public_courses.step(
        course_id, step_id
    )
    return view

"""Use cases: published courses read by guests (nobody signed in)."""

from copy import deepcopy
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.lms.application.learning.attempt_presenter import number
from app.modules.lms.application.learning.course_page import (
    CoursePageBuilder,
    course_card,
)
from app.modules.lms.application.learning.get_step_view import (
    NEW_BLOCK_TYPES,
    scored_block,
    widget_block,
)
from app.modules.lms.application.learning.revision_loading import load_rendered
from app.modules.lms.application.learning.step_context import load_live_step
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import (
    LearningAiReviewBlockView,
    LearningCourseCardView,
    LearningFlashcardsBlockView,
    LearningGuestCoursePageView,
    LearningQuizBlockView,
    LearningQuizRulesView,
    LearningStepView,
    LearningTextBlockView,
    LearningVideoBlockView,
    StepBlockView,
)
from app.modules.lms.domain.access_rules import AccessState
from app.modules.lms.domain.learning.errors import CourseNotFoundError
from app.modules.lms.domain.learning.landing import (
    publicly_viewable,
    within_enrolment_window,
)
from app.modules.lms.domain.learning.live import RenderCache, RenderedRevision
from app.shared.clock import Clock

CATALOG_LIMIT = 200


class PublicCourses:
    """Read the catalogue, a course page and a lesson without signing in.

    Every method checks `publicly_viewable` and the audience rules for a guest;
    a course or lesson that fails them looks missing (hidden) or locked (403).
    Nothing is written and nothing personal (progress, attempts, answers) is read.
    """

    def __init__(
        self,
        uow_factory: UowFactory,
        builder: CoursePageBuilder,
        cache: RenderCache,
        clock: Clock,
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.builder = builder
        self.cache = cache
        self.clock = clock

    async def catalog(self, query: str | None = None) -> list[LearningCourseCardView]:
        """Return the publicly viewable courses, optionally filtered by title."""
        async with self.uow_factory() as uow:
            courses = [
                c
                for c in await uow.courses.search_published(
                    (query or "").strip() or None, limit=CATALOG_LIMIT
                )
                if publicly_viewable(c)
            ]
            access = await self.builder.gate.courses(uow, None, [c.id for c in courses])
            courses = [
                c for c in courses if access[c.id].state is not AccessState.HIDDEN
            ]
            versions = await uow.versions.get_many(
                [c.live_version_id for c in courses if c.live_version_id is not None]
            )
        return [
            course_card(
                c,
                versions.get(c.live_version_id) if c.live_version_id else None,
                progress_pct=None,
                access=access[c.id],
            )
            for c in courses
        ]

    async def page(self, slug: str) -> LearningGuestCoursePageView:
        """Return the course page for a guest; `slug` may also be the course id.

        The player's address carries the id, so it can ask for the outline too.
        """
        async with self.uow_factory() as uow:
            course = (
                await uow.courses.get(identifier)
                if (identifier := _as_uuid(slug))
                else await uow.courses.get_by_slug(slug)
            )
            if course is None or not publicly_viewable(course):
                raise CourseNotFoundError(params={"slug": slug})
            return await self.builder.build_guest(uow, course)

    async def step(self, course_id: UUID, step_id: UUID) -> LearningStepView:
        """Return a lesson of a public course with no personal state.

        A course with an enrolment window shows its lessons to guests only
        while the window is open; outside it the lesson looks missing.
        """
        async with self.uow_factory() as uow:
            context = await load_live_step(uow, step_id)
            course = context.course
            if (
                course.id != course_id
                or not publicly_viewable(course)
                or not within_enrolment_window(course, self.clock.now())
            ):
                raise CourseNotFoundError(params={"course_id": str(course_id)})
            await self.builder.gate.require_step(uow, None, course_id, step_id)
            rendered = await load_rendered(
                uow, self.cache, context.live_step.revision_id
            )
        blocks = [_guest_block(block, rendered) for block in deepcopy(rendered.blocks)]
        return LearningStepView(
            step_id=step_id,
            revision_id=rendered.revision_id,
            title=rendered.title,
            blocks=blocks,
            completed=False,
            preview=False,
            blocks_total=len(blocks),
            blocks_passed=0,
            points_total=number(rendered.points_total),
            points_earned=0.0,
        )


def _guest_block(block: dict[str, Any], rendered: RenderedRevision) -> StepBlockView:
    """Fill a cached render block with empty personal state."""
    kind = block["type"]
    if kind == "test":
        rules = dict(block["rules"])
        total = rendered.test_points.get(str(block["id"]), Decimal(0))
        return LearningQuizBlockView(
            id=str(block["id"]),
            type="test",
            rules=LearningQuizRulesView(**rules),
            best=None,
            open_attempt_id=None,
            passed=False,
            points_total=number(total),
            points_earned=0.0,
        )
    if kind == "flashcards":
        return LearningFlashcardsBlockView(
            id=str(block["id"]),
            type="flashcards",
            cards_count=int(block["cards_count"]),
            due=0,
            passed=False,
        )
    if kind in ("h5p", "interactive_video"):
        return scored_block(block, None)
    if kind in NEW_BLOCK_TYPES:
        return widget_block(block)
    if kind == "ai_review":
        return LearningAiReviewBlockView(**block)
    if kind == "video":
        return LearningVideoBlockView(**block, passed=False)
    return LearningTextBlockView(**block, passed=False)


def _as_uuid(value: str) -> UUID | None:
    """Parse a UUID, or return None when the text is a slug."""
    try:
        return UUID(value)
    except ValueError:
        return None

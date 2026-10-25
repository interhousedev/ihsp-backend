"""Use case: join an invite-only course with its code (UF-LMS-02)."""

from typing import Final

from app.modules.lms.application.learning.course_page import CoursePageBuilder
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import LearningCoursePageView
from app.modules.lms.domain.learning.errors import InviteNotValidError
from app.shared.actor import Actor
from app.shared.rate_limit import RateLimiter
from app.shared.tasks import TaskKicker

JOIN_LIMIT: Final = 10
JOIN_WINDOW_SECONDS: Final = 3600


class JoinCourse:
    """Enroll through an invite code; every try counts against a rate limit."""

    def __init__(
        self,
        uow_factory: UowFactory,
        builder: CoursePageBuilder,
        rate_limiter: RateLimiter,
        kicker: TaskKicker | None = None,
    ) -> None:
        """Store collaborators (`kicker` starts the student's course notebook)."""
        self.uow_factory = uow_factory
        self.builder = builder
        self.rate_limiter = rate_limiter
        self.kicker = kicker

    async def execute(self, actor: Actor, code: str) -> LearningCoursePageView:
        """Return the course page after joining; a wrong code is a 404."""
        await self.rate_limiter.hit(
            f"lms-join:{actor.user_id}",
            limit=JOIN_LIMIT,
            window_seconds=JOIN_WINDOW_SECONDS,
        )
        async with self.uow_factory() as uow:
            course = await uow.courses.get_by_invite_code(code.strip())
            if (
                course is None
                or course.visibility != "invite"
                or not course.is_open_for_students
            ):
                raise InviteNotValidError()
            enrollment = await uow.enrollments.add(
                course_id=course.id, user_id=actor.user_id, via="invite"
            )
            page = await self.builder.build(uow, actor, course, enrollment)
            await uow.commit()
            course_id = course.id
        if self.kicker is not None:
            await self.kicker.kick(
                "notebooks.provision_course_notebook",
                user_id=str(actor.user_id),
                course_id=str(course_id),
            )
        return page

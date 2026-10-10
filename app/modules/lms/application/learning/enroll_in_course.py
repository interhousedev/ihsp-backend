"""Use case: enroll in a public course (UF-LMS-01 step 4)."""

from uuid import UUID

from app.modules.lms.application.learning.course_page import CoursePageBuilder
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import LearningCoursePageView
from app.modules.lms.domain.learning.errors import CourseNotFoundError
from app.shared.actor import Actor
from app.shared.tasks import TaskKicker


class EnrollInCourse:
    """Enroll the actor in a published, active, public course."""

    def __init__(
        self,
        uow_factory: UowFactory,
        builder: CoursePageBuilder,
        kicker: TaskKicker | None = None,
    ) -> None:
        """Store collaborators (`kicker` starts the student's course notebook)."""
        self.uow_factory = uow_factory
        self.builder = builder
        self.kicker = kicker

    async def execute(self, actor: Actor, course_id: UUID) -> LearningCoursePageView:
        """Enroll (once) and return the course page; other courses look missing."""
        async with self.uow_factory() as uow:
            course = await uow.courses.get(course_id)
            if (
                course is None
                or not course.is_open_for_students
                or course.visibility != "public"
            ):
                raise CourseNotFoundError(params={"course_id": str(course_id)})
            enrollment = await uow.enrollments.add(
                course_id=course.id, user_id=actor.user_id, via="self"
            )
            page = await self.builder.build(uow, actor, course, enrollment)
            await uow.commit()
        if self.kicker is not None:
            await self.kicker.kick(
                "notebooks.provision_course_notebook",
                user_id=str(actor.user_id),
                course_id=str(course_id),
            )
        return page

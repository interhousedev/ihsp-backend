"""Use case: open a course page (UF-LMS-01 step 3, UF-LMS-05)."""

from app.modules.lms.application.learning.course_page import CoursePageBuilder
from app.modules.lms.application.learning.step_context import staff_access
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import LearningCoursePageView
from app.modules.lms.domain.learning.entities import Enrollment, LearningCourse
from app.modules.lms.domain.learning.errors import CourseNotFoundError
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork
from app.shared.actor import Actor


class GetCoursePage:
    """Show a course to someone who may see it."""

    def __init__(self, uow_factory: UowFactory, builder: CoursePageBuilder) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.builder = builder

    async def execute(self, actor: Actor, slug: str) -> LearningCoursePageView:
        """Return the page; invite-only courses are hidden from non-members."""
        async with self.uow_factory() as uow:
            course = await uow.courses.get_by_slug(slug)
            if course is None:
                raise CourseNotFoundError(params={"slug": slug})
            enrollment = await uow.enrollments.get(course.id, actor.user_id)
            await self._check_visible(uow, actor, course, enrollment)
            page = await self.builder.build(uow, actor, course, enrollment)
            await uow.commit()
        return page

    async def _check_visible(
        self,
        uow: LearningUnitOfWork,
        actor: Actor,
        course: LearningCourse,
        enrollment: Enrollment | None,
    ) -> None:
        """Raise CourseNotFoundError unless the actor may see the course."""
        if enrollment is not None:
            return
        if course.is_open_for_students and course.visibility == "public":
            return
        if (await staff_access(uow, actor, course.id)).is_staff:
            return
        raise CourseNotFoundError(params={"slug": course.slug})

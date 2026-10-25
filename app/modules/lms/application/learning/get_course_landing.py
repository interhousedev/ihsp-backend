"""Use case: the landing page of a course (UF-LMS-01)."""

from app.modules.lms.application.learning.step_context import staff_access
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import (
    LearningLandingAuthorView,
    LearningLandingEnrolmentView,
    LearningLandingSectionView,
    LearningLandingStepView,
    LearningLandingView,
    LearningPersonRefView,
)
from app.modules.lms.domain.learning.access import EDIT
from app.modules.lms.domain.learning.errors import CourseNotFoundError
from app.modules.lms.domain.learning.landing import can_enrol, landing_visible
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory


def _file_url(file_id: object) -> str | None:
    return f"/files/{file_id}" if file_id else None


class GetCourseLanding:
    """Describe a course to someone deciding whether to take it."""

    def __init__(
        self, uow_factory: UowFactory, identity: IdentityDirectory, clock: Clock
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.identity = identity
        self.clock = clock

    async def execute(
        self, actor: Actor, slug: str, *, preview: bool = False
    ) -> LearningLandingView:
        """Return the landing; hidden courses look missing (404)."""
        async with self.uow_factory() as uow:
            course = await uow.courses.get_by_slug(slug)
            if course is None:
                raise CourseNotFoundError(params={"slug": slug})
            access = await staff_access(uow, actor, course.id)
            enrollment = await uow.enrollments.get(course.id, actor.user_id)
            previewing = preview and access.can(EDIT)
            if not landing_visible(
                course,
                enrolled=enrollment is not None,
                is_staff=access.is_staff,
                previewing=previewing,
            ):
                raise CourseNotFoundError(params={"slug": slug})
            version = (
                await uow.versions.get(course.live_version_id)
                if course.live_version_id
                else None
            )
            members = await uow.staff.list_on_page(course.id)
        users = await self.identity.get_users([m.user_id for m in members])
        enrolled = enrollment is not None
        return LearningLandingView(
            id=course.id,
            slug=course.slug,
            title=course.title,
            friendly_name=course.friendly_name,
            summary=course.summary,
            description=course.description,
            cover_file_id=course.cover_file_id,
            cover_url=_file_url(course.cover_file_id),
            banner_file_id=course.banner_file_id,
            banner_url=_file_url(course.banner_file_id),
            accent_color=course.accent_color,
            language=course.language,
            level=course.level,
            workload_hours_per_week=course.workload_hours_per_week,
            duration_weeks=course.duration_weeks,
            tags=list(course.tags),
            outcomes=list(course.outcomes),
            requirements=list(course.requirements),
            audience=list(course.audience),
            publish_state=course.publish_state,
            preview=previewing,
            authors=[
                LearningLandingAuthorView(
                    user=LearningPersonRefView(
                        id=u.id, first_name=u.first_name, last_name=u.last_name
                    ),
                    role=m.role,
                )
                for m in members
                if (u := users.get(m.user_id)) is not None
            ],
            syllabus=[
                LearningLandingSectionView(
                    title=section.title,
                    steps=[
                        LearningLandingStepView(title=s.title) for s in section.steps
                    ],
                )
                for section in (version.manifest.sections if version else [])
            ],
            enrolment=LearningLandingEnrolmentView(
                open=course.enrolment_open,
                starts_at=course.enrolment_starts_at,
                ends_at=course.enrolment_ends_at,
                can_enrol=can_enrol(course, enrolled=enrolled, now=self.clock.now()),
                enrolled=enrolled,
            ),
        )

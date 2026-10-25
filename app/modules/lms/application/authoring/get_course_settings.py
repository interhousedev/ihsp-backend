"""Use case: read the settings page of a course."""

from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_course
from app.modules.lms.application.authoring.settings_views import (
    CourseSettingsView,
    SettingsStatsView,
)
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.domain.authoring.course_settings import (
    derive_publish_state,
    to_settings,
)
from app.modules.lms.domain.authoring.entities import Course
from app.modules.lms.domain.authoring.outline import sections_of
from app.modules.lms.domain.authoring.permissions import EDIT
from app.modules.lms.ports.authoring.unit_of_work import AuthoringUnitOfWork
from app.shared.actor import Actor


async def settings_view(uow: AuthoringUnitOfWork, course: Course) -> CourseSettingsView:
    """Build the settings view with counts of sections, steps, learners, staff."""
    settings = to_settings(course)
    sections = sections_of(course.draft_outline)
    staff_by_role: dict[str, int] = {}
    for member in await uow.staff.list_for_course(course.id):
        staff_by_role[member.role] = staff_by_role.get(member.role, 0) + 1
    return CourseSettingsView(
        id=course.id,
        slug=course.slug,
        lock_version=course.lock_version,
        cover_file_id=course.cover_file_id,
        banner_file_id=course.banner_file_id,
        publish_state=derive_publish_state(course),
        visibility=course.visibility.value,
        invite_code=course.invite_code,
        stats=SettingsStatsView(
            sections=len(sections),
            steps=sum(len(section["steps"]) for section in sections),
            learners=await uow.courses.count_learners(course.id),
            staff_by_role=staff_by_role,
        ),
        **vars_of(settings),
    )


def vars_of(settings: object) -> dict[str, object]:
    """Return the dataclass fields as keyword arguments."""
    names: tuple[str, ...] = settings.__slots__  # type: ignore[attr-defined]
    return {name: getattr(settings, name) for name in names}


class GetCourseSettings:
    """Show the settings to someone who can edit the course."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, course_id: UUID) -> CourseSettingsView:
        """Return the settings of the course."""
        async with self.uow_factory() as uow:
            course = await load_course(uow, course_id)
            (await access_to(uow, actor, course_id)).require(EDIT)
            return await settings_view(uow, course)

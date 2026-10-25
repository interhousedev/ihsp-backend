"""Building course cards and course pages (LMS-4, UF-LMS-01, UF-LMS-05)."""

from datetime import datetime
from uuid import UUID

from app.modules.lms.application.learning.attempt_presenter import number
from app.modules.lms.application.learning.progress_service import ensure_progress
from app.modules.lms.application.learning.step_context import staff_access
from app.modules.lms.application.learning.step_points import (
    CoursePoints,
    load_course_points,
)
from app.modules.lms.application.learning.views import (
    LearningCourseCardView,
    LearningCoursePageView,
    LearningCourseStaffItemView,
    LearningOutlineSectionView,
    LearningOutlineStepView,
    LearningPersonRefView,
)
from app.modules.lms.domain.learning.access import EDIT, ordered_permissions
from app.modules.lms.domain.learning.entities import (
    Enrollment,
    LearningCourse,
    LiveVersion,
    StaffMember,
)
from app.modules.lms.domain.learning.live import (
    RenderCache,
    StepChange,
    changes_between,
)
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory, UserRef


def course_card(
    course: LearningCourse,
    version: LiveVersion | None,
    *,
    progress_pct: int | None,
) -> LearningCourseCardView:
    """Return a course for lists; the outline is counted from the live version."""
    return LearningCourseCardView(
        id=course.id,
        slug=course.slug,
        title=course.title,
        description=course.description,
        cover_url=f"/files/{course.cover_file_id}" if course.cover_file_id else None,
        steps_count=len(version.manifest.step_ids()) if version else 0,
        progress_pct=progress_pct,
        visibility="invite" if course.visibility == "invite" else "public",
        updated_at=version.created_at if version else None,
        summary=course.summary,
        accent_color=course.accent_color,
        cover_file_id=course.cover_file_id,
    )


def _person(user: UserRef) -> LearningPersonRefView:
    """Return the public name of a user."""
    return LearningPersonRefView(
        id=user.id, first_name=user.first_name, last_name=user.last_name
    )


class CoursePageBuilder:
    """Builds `CoursePage`, keeping progress and "last seen version" up to date."""

    def __init__(
        self, identity: IdentityDirectory, clock: Clock, cache: RenderCache
    ) -> None:
        """Store collaborators; ``cache`` holds the renders the points come from."""
        self.identity = identity
        self.clock = clock
        self.cache = cache

    async def build(
        self,
        uow: LearningUnitOfWork,
        actor: Actor,
        course: LearningCourse,
        enrollment: Enrollment | None,
    ) -> LearningCoursePageView:
        """Return the page for the actor; writes progress and last seen version."""
        now = self.clock.now()
        version = await self._version(uow, course)
        access = await staff_access(uow, actor, course.id)
        changes = await self._visit(uow, enrollment, version, now)
        completed = await self._completed(uow, actor, enrollment, version)
        points = await self._points(uow, actor, enrollment, version)
        card = course_card(
            course,
            version,
            progress_pct=enrollment.progress_pct if enrollment else None,
        )
        return LearningCoursePageView(
            **card.model_dump(),
            staff=await self._staff(uow, course.id),
            outline=_outline(
                version, completed, changes, points, enrolled=enrollment is not None
            ),
            enrolled=enrollment is not None,
            can_edit=access.can(EDIT),
            changed_since_last_visit=list(changes),
            steps_completed=len(completed) if enrollment else None,
            points_total=number(points.total),
            points_earned=number(points.earned) if enrollment else None,
        )

    async def _version(
        self, uow: LearningUnitOfWork, course: LearningCourse
    ) -> LiveVersion | None:
        """Return the live version of the course, if it has one."""
        if course.live_version_id is None:
            return None
        return await uow.versions.get(course.live_version_id)

    async def _visit(
        self,
        uow: LearningUnitOfWork,
        enrollment: Enrollment | None,
        version: LiveVersion | None,
        now: datetime,
    ) -> dict[UUID, StepChange]:
        """Refresh progress, report steps changed since the last visit, remember."""
        if enrollment is None or version is None:
            return {}
        await ensure_progress(uow, enrollment, version, now)
        changes: dict[UUID, StepChange] = {}
        seen_id = enrollment.last_seen_version_id
        if seen_id is not None and seen_id != version.id:
            seen = await uow.versions.get(seen_id)
            changes = changes_between(seen.manifest, version.manifest) if seen else {}
        if seen_id != version.id:
            enrollment.last_seen_version_id = version.id
            await uow.enrollments.save(enrollment)
        return changes

    async def _completed(
        self,
        uow: LearningUnitOfWork,
        actor: Actor,
        enrollment: Enrollment | None,
        version: LiveVersion | None,
    ) -> set[UUID]:
        """Return the steps the actor completed (empty when not enrolled)."""
        if enrollment is None or version is None:
            return set()
        return await uow.states.completed_step_ids(
            actor.user_id, version.manifest.step_ids()
        )

    async def _points(
        self,
        uow: LearningUnitOfWork,
        actor: Actor,
        enrollment: Enrollment | None,
        version: LiveVersion | None,
    ) -> CoursePoints:
        """Return the points of the live version and, when enrolled, the earned ones."""
        if version is None:
            return CoursePoints(steps={})
        user_id = actor.user_id if enrollment is not None else None
        return await load_course_points(uow, self.cache, version, user_id)

    async def _staff(
        self, uow: LearningUnitOfWork, course_id: UUID
    ) -> list[LearningCourseStaffItemView]:
        """Return the staff members shown on the course page."""
        members = await uow.staff.list_on_page(course_id)
        users = await self.identity.get_users([member.user_id for member in members])
        return [
            _staff_item(member, users[member.user_id])
            for member in members
            if member.user_id in users
        ]


def _staff_item(member: StaffMember, user: UserRef) -> LearningCourseStaffItemView:
    """Return one staff member of the course page."""
    return LearningCourseStaffItemView(
        user=_person(user),
        role=member.role,
        permissions=ordered_permissions(member.permissions),
        show_on_page=member.show_on_page,
        position=member.position,
    )


def _outline(
    version: LiveVersion | None,
    completed: set[UUID],
    changes: dict[UUID, StepChange],
    points: CoursePoints,
    *,
    enrolled: bool,
) -> list[LearningOutlineSectionView]:
    """Return the outline of the live version with completion and change marks."""
    if version is None:
        return []
    return [
        LearningOutlineSectionView(
            id=section.id,
            title=section.title,
            steps=[
                LearningOutlineStepView(
                    step_id=step.step_id,
                    title=step.title,
                    completed=(step.step_id in completed) if enrolled else None,
                    badge=changes.get(step.step_id),
                    points_total=number(points.steps[step.step_id].total),
                    points_earned=(
                        number(points.steps[step.step_id].earned) if enrolled else None
                    ),
                )
                for step in section.steps
            ],
        )
        for section in version.manifest.sections
    ]

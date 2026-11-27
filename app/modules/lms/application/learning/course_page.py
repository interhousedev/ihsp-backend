"""Building course cards and course pages (LMS-4, UF-LMS-01, UF-LMS-05)."""

from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from app.modules.lms.application.learning.attempt_presenter import number
from app.modules.lms.application.learning.audience import AudienceGate, CourseAccess
from app.modules.lms.application.learning.progress_service import ensure_progress
from app.modules.lms.application.learning.step_context import staff_access
from app.modules.lms.application.learning.step_points import (
    CoursePoints,
    load_course_points,
)
from app.modules.lms.application.learning.views import (
    LearningContactView,
    LearningCourseCardView,
    LearningCoursePageView,
    LearningCourseStaffItemView,
    LearningGuestCoursePageView,
    LearningGuestStaffItemView,
    LearningOutlineSectionView,
    LearningOutlineStepView,
    LearningPersonRefView,
)
from app.modules.lms.domain.access_rules import AccessState, Audience
from app.modules.lms.domain.engagement.errors import SectionLockedError
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
    access: CourseAccess,
) -> LearningCourseCardView:
    """Return a course for lists; only the steps the viewer sees are counted."""
    return LearningCourseCardView(
        id=course.id,
        slug=course.slug,
        title=course.title,
        description=course.description,
        cover_url=f"/files/{course.cover_file_id}" if course.cover_file_id else None,
        steps_count=len(access.visible(version.manifest.step_ids())) if version else 0,
        progress_pct=progress_pct,
        visibility="invite" if course.visibility == "invite" else "public",
        updated_at=version.created_at if version else None,
        summary=course.summary,
        accent_color=course.accent_color,
        cover_file_id=course.cover_file_id,
        locked=access.state is AccessState.LOCKED,
        access=access.audience.value,
    )


def _person(user: UserRef) -> LearningPersonRefView:
    """Return the public name of a user."""
    return LearningPersonRefView(
        id=user.id, first_name=user.first_name, last_name=user.last_name
    )


class CoursePageBuilder:
    """Builds `CoursePage`, keeping progress and "last seen version" up to date."""

    def __init__(
        self,
        identity: IdentityDirectory,
        clock: Clock,
        cache: RenderCache,
        gate: AudienceGate,
    ) -> None:
        """Store collaborators; ``cache`` holds the renders the points come from."""
        self.identity = identity
        self.clock = clock
        self.cache = cache
        self.gate = gate

    async def build(
        self,
        uow: LearningUnitOfWork,
        actor: Actor,
        course: LearningCourse,
        enrollment: Enrollment | None,
    ) -> LearningCoursePageView:
        """Return the page for the actor; writes progress and last seen version."""
        audience = await self.gate.require_visible(uow, actor, course.id)
        now = self.clock.now()
        version = await self._version(uow, course)
        access = await staff_access(uow, actor, course.id)
        changes = await self._visit(uow, enrollment, version, now)
        completed = await self._completed(uow, actor, enrollment, version, audience)
        points = await self._points(uow, actor, enrollment, version, audience)
        card = course_card(
            course,
            version,
            progress_pct=enrollment.progress_pct if enrollment else None,
            access=audience,
        )
        locked_sections = await self._mastery_locked(
            actor, course, version, audience, enrolled=enrollment is not None
        )
        outline = _outline(
            version,
            completed,
            changes,
            points,
            audience,
            enrolled=enrollment is not None,
            mastery_locked=locked_sections,
        )
        return LearningCoursePageView(
            **card.model_dump(),
            staff=await self._staff(uow, course.id),
            outline=outline,
            enrolled=enrollment is not None,
            enrolled_via=enrollment.via if enrollment else None,
            continue_step_id=_continue_step(outline) if enrollment else None,
            can_edit=access.can(EDIT),
            changed_since_last_visit=list(changes),
            steps_completed=len(completed) if enrollment else None,
            points_total=number(points.total),
            points_earned=number(points.earned) if enrollment else None,
            contact=await self._contact(uow, course.id, audience, signed_in=True),
        )

    async def build_guest(
        self, uow: LearningUnitOfWork, course: LearningCourse
    ) -> LearningGuestCoursePageView:
        """Return the page for a guest: no progress, no writes, nothing personal."""
        audience = await self.gate.require_visible(uow, None, course.id)
        version = await self._version(uow, course)
        points = (
            await load_course_points(uow, self.cache, version, None, audience)
            if version is not None
            else CoursePoints(steps={})
        )
        card = course_card(course, version, progress_pct=None, access=audience)
        return LearningGuestCoursePageView(
            **card.model_dump(),
            staff=[
                LearningGuestStaffItemView(name=_name(user), position=member.position)
                for member, user in await self._members(uow, course.id)
            ],
            outline=_outline(version, set(), {}, points, audience, enrolled=False),
            enrolled=False,
            can_edit=False,
            changed_since_last_visit=[],
            steps_completed=None,
            points_total=number(points.total),
            points_earned=None,
            contact=await self._contact(uow, course.id, audience, signed_in=False),
        )

    async def _mastery_locked(
        self,
        actor: Actor,
        course: LearningCourse,
        version: LiveVersion | None,
        audience: CourseAccess,
        *,
        enrolled: bool,
    ) -> set[str]:
        """Return the sections the mastery threshold still locks (one check each)."""
        locked: set[str] = set()
        if not enrolled or version is None or self.gate.step_lock is None:
            return locked
        for section in version.manifest.sections:
            first = next(
                (
                    s.step_id
                    for s in section.steps
                    if audience.step(s.step_id) is not AccessState.HIDDEN
                ),
                None,
            )
            if first is None:
                continue
            try:
                await self.gate.step_lock(actor, course.id, first)
            except SectionLockedError:
                locked.add(section.id)
        return locked

    async def _contact(
        self,
        uow: LearningUnitOfWork,
        course_id: UUID,
        audience: CourseAccess,
        *,
        signed_in: bool,
    ) -> LearningContactView | None:
        """Return whom to ask for access when a chosen-audience item is locked."""
        if not audience.needs_contact:
            return None
        return await self.gate.contact(uow, course_id, signed_in=signed_in)

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
        await ensure_progress(uow, self.gate, enrollment, version, now)
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
        audience: CourseAccess,
    ) -> set[UUID]:
        """Return the visible steps the actor completed (empty when not enrolled)."""
        if enrollment is None or version is None:
            return set()
        return await uow.states.completed_step_ids(
            actor.user_id, audience.visible(version.manifest.step_ids())
        )

    async def _points(
        self,
        uow: LearningUnitOfWork,
        actor: Actor,
        enrollment: Enrollment | None,
        version: LiveVersion | None,
        audience: CourseAccess,
    ) -> CoursePoints:
        """Return the points of the visible steps and, if enrolled, the earned ones."""
        if version is None:
            return CoursePoints(steps={})
        user_id = actor.user_id if enrollment is not None else None
        return await load_course_points(uow, self.cache, version, user_id, audience)

    async def _members(
        self, uow: LearningUnitOfWork, course_id: UUID
    ) -> list[tuple[StaffMember, UserRef]]:
        """Return the staff members shown on the course page with their users."""
        members = await uow.staff.list_on_page(course_id)
        users = await self.identity.get_users([member.user_id for member in members])
        return [
            (member, users[member.user_id])
            for member in members
            if member.user_id in users
        ]

    async def _staff(
        self, uow: LearningUnitOfWork, course_id: UUID
    ) -> list[LearningCourseStaffItemView]:
        """Return the staff members shown on the course page."""
        return [
            _staff_item(member, user)
            for member, user in await self._members(uow, course_id)
        ]


def _name(user: UserRef) -> str:
    """Return the display name of a user."""
    return f"{user.first_name} {user.last_name}".strip()


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
    audience: CourseAccess,
    *,
    enrolled: bool,
    mastery_locked: Collection[str] = frozenset(),
) -> list[LearningOutlineSectionView]:
    """Return the outline with completion and change marks; hidden steps drop out."""
    if version is None:
        return []
    sections = []
    for section in version.manifest.sections:
        steps = []
        for step in section.steps:
            state = audience.step(step.step_id)
            if state is AccessState.HIDDEN:
                continue
            access_locked = state is AccessState.LOCKED
            mastery = section.id in mastery_locked and not access_locked
            steps.append(
                LearningOutlineStepView(
                    step_id=step.step_id,
                    title=step.title,
                    completed=(step.step_id in completed) if enrolled else None,
                    badge=changes.get(step.step_id),
                    points_total=number(points.steps[step.step_id].total),
                    points_earned=(
                        number(points.steps[step.step_id].earned) if enrolled else None
                    ),
                    locked=access_locked or mastery,
                    lock_reason=(
                        "access" if access_locked else "mastery" if mastery else None
                    ),
                    access=audience.step_audiences.get(
                        step.step_id, Audience.PUBLIC
                    ).value,
                    kind=points.steps[step.step_id].kind,
                    estimated_minutes=points.steps[step.step_id].minutes,
                )
            )
        if steps:
            sections.append(
                LearningOutlineSectionView(
                    id=section.id, title=section.title, steps=steps
                )
            )
    return sections


def _continue_step(outline: list[LearningOutlineSectionView]) -> UUID | None:
    """Return the first open step to resume at, else the first step."""
    steps = [s for section in outline for s in section.steps if not s.locked]
    for step in steps:
        if not step.completed:
            return step.step_id
    return steps[0].step_id if steps else None

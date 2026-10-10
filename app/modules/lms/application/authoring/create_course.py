"""Use case: create a course with an empty draft (LMS-21, UF-LMS-06)."""

from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import CourseDraftView
from app.modules.lms.domain.authoring.course_rules import (
    clean_title,
    new_invite_code,
    validate_slug,
)
from app.modules.lms.domain.authoring.entities import Course, StaffMember
from app.modules.lms.domain.authoring.enums import CourseStatus, Visibility
from app.modules.lms.domain.authoring.errors import (
    CoursePermissionError,
    SlugTakenError,
)
from app.modules.lms.domain.authoring.hashing import outline_hash
from app.modules.lms.domain.authoring.outline import empty_outline
from app.modules.lms.domain.authoring.permissions import (
    PERMISSIONS,
    CourseAccess,
    ordered,
)
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.lms_scopes import COURSES_WRITE, scope_allows


class CreateCourse:
    """Create a course that students cannot see yet (LMS admins and course creators).

    A course creator becomes the owner of the course; an LMS admin already holds
    every permission, so no staff row is added for them.
    """

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, presenter: Presenter
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.presenter = presenter

    async def execute(
        self, actor: Actor, *, title: str, slug: str, visibility: Visibility
    ) -> CourseDraftView:
        """Create the course with an empty outline and no live version."""
        actor.require(Role.LMS_ADMIN, Role.LMS_CREATOR)
        if not scope_allows(actor.scopes, COURSES_WRITE):
            raise CoursePermissionError(params={"permission": COURSES_WRITE})
        clean = clean_title(title)
        validate_slug(slug)
        meta = {"title": clean, "description": ""}
        outline = empty_outline()
        course = Course(
            id=new_id(),
            slug=slug,
            title=clean,
            description="",
            visibility=visibility,
            status=CourseStatus.ACTIVE,
            created_by=actor.user_id,
            draft_meta=meta,
            draft_outline=outline,
            outline_hash=outline_hash(meta, outline),
            invite_code=new_invite_code() if visibility is Visibility.INVITE else None,
            draft_updated_by=actor.user_id,
            draft_updated_at=self.clock.now(),
        )
        owner = None if actor.has(Role.LMS_ADMIN) else _owner_of(course, actor)
        async with self.uow_factory() as uow:
            if await uow.courses.slug_exists(slug):
                raise SlugTakenError(params={"slug": slug})
            await uow.courses.add(course)
            if owner is not None:
                await uow.staff.add(owner)
            await uow.commit()
            return await self.presenter.course_draft(
                uow, course, CourseAccess(actor=actor, staff=owner)
            )


def _owner_of(course: Course, actor: Actor) -> StaffMember:
    """The creator's staff row: every permission, not shown on the course page."""
    return StaffMember(
        course_id=course.id,
        user_id=actor.user_id,
        role="owner",
        permissions=ordered(PERMISSIONS),
        show_on_page=False,
        position=0,
        added_by=actor.user_id,
    )

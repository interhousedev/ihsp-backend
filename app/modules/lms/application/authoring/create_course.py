"""Use case: create a course with an empty draft (LMS-21, UF-LMS-06)."""

from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import CourseDraftView
from app.modules.lms.domain.authoring.course_rules import (
    clean_title,
    new_invite_code,
    validate_slug,
)
from app.modules.lms.domain.authoring.entities import Course
from app.modules.lms.domain.authoring.enums import CourseStatus, Visibility
from app.modules.lms.domain.authoring.errors import SlugTakenError
from app.modules.lms.domain.authoring.hashing import outline_hash
from app.modules.lms.domain.authoring.outline import empty_outline
from app.modules.lms.domain.authoring.permissions import CourseAccess
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.ids import new_id


class CreateCourse:
    """Create a course that students cannot see yet (LMS admins only)."""

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
        actor.require(Role.LMS_ADMIN)
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
        async with self.uow_factory() as uow:
            if await uow.courses.slug_exists(slug):
                raise SlugTakenError(params={"slug": slug})
            await uow.courses.add(course)
            await uow.commit()
            return await self.presenter.course_draft(
                uow, course, CourseAccess(actor=actor, staff=None)
            )

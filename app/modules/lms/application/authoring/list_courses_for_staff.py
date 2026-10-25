"""Use case: courses where a user holds a permission (MCP course picker)."""

from typing import Any
from uuid import UUID

from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.domain.authoring.entities import Course
from app.modules.lms.domain.authoring.errors import StaffInvalidError
from app.modules.lms.domain.authoring.permissions import PERMISSIONS
from app.shared.actor import Role
from app.shared.contracts.identity import IdentityDirectory


class ListCoursesForStaff:
    """List courses the user can act on; LMS admins see every course."""

    def __init__(self, uow_factory: UowFactory, identity: IdentityDirectory) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.identity = identity

    async def execute(self, user_id: UUID, permission: str) -> list[dict[str, Any]]:
        """Return `{id, slug, title, status, visibility, published}` per course."""
        if permission not in PERMISSIONS:
            raise StaffInvalidError(params={"unknown": [permission]})
        user = await self.identity.get_user(user_id)
        is_admin = user is not None and Role.LMS_ADMIN in user.roles
        async with self.uow_factory() as uow:
            if is_admin:
                courses = await uow.courses.list_all()
            else:
                courses = await uow.courses.list_for_user(user_id, permission)
        return [_summary(course) for course in courses]


def _summary(course: Course) -> dict[str, Any]:
    return {
        "id": str(course.id),
        "slug": course.slug,
        "title": course.draft_meta.get("title", course.title),
        "status": course.status.value,
        "visibility": course.visibility.value,
        "published": course.live_version_id is not None,
        "summary": course.summary,
        "accent_color": course.accent_color,
        "cover_file_id": str(course.cover_file_id) if course.cover_file_id else None,
    }

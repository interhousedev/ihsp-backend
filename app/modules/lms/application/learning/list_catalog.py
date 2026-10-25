"""Use case: the catalog of published public courses (UF-LMS-01)."""

from typing import Final

from app.modules.lms.application.learning.course_page import course_card
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import LearningCourseCardView

CATALOG_LIMIT: Final = 200


class ListCatalog:
    """List the courses anyone can enroll in."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory

    async def execute(
        self, *, query: str | None = None
    ) -> list[LearningCourseCardView]:
        """Return published, active, public courses, optionally filtered by title."""
        async with self.uow_factory() as uow:
            courses = await uow.courses.search_published(
                (query or "").strip() or None, limit=CATALOG_LIMIT
            )
            versions = await uow.versions.get_many(
                [c.live_version_id for c in courses if c.live_version_id is not None]
            )
        return [
            course_card(
                course,
                (
                    versions.get(course.live_version_id)
                    if course.live_version_id
                    else None
                ),
                progress_pct=None,
            )
            for course in courses
        ]

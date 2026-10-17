"""Use case: copy a course draft by exporting and re-importing it in-process.

The export carries ``ihsp/course.json``, so the round trip keeps the exact step
content; files are copied as new files owned by the caller.
"""

from dataclasses import dataclass
from uuid import UUID

from app.modules.lms.application.cartridge.export_cartridge import ExportCartridge
from app.modules.lms.application.cartridge.import_cartridge import ImportCartridge
from app.shared.actor import Actor


@dataclass(frozen=True, slots=True)
class CopiedCourse:
    """The new draft course."""

    course_id: UUID
    title: str


class CopyCourse:
    """Create "<title> (copy)" owned by the caller, as a draft."""

    def __init__(self, exporter: ExportCartridge, importer: ImportCartridge) -> None:
        """Store collaborators."""
        self.exporter = exporter
        self.importer = importer

    async def execute(self, actor: Actor, course_id: UUID) -> CopiedCourse:
        """Copy the course.

        Raises:
            CourseNotFoundError: No such course.
            CoursePermissionError: The actor may not edit the course.
            ForbiddenError: The actor may not create courses.
        """
        exported = await self.exporter.execute(actor, course_id)
        title = f"{exported.title} (copy)"[:200]
        outcome = await self.importer.execute(actor, exported.data, title=title)
        return CopiedCourse(course_id=outcome.course_id, title=title)

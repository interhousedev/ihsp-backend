"""The course gate over the LMS contract, and the gate of a process without the LMS."""

from uuid import UUID

from app.settings import Settings
from app.shared.contracts.lms import CourseWorkspaceAccess, LmsWorkspace
from app.shared.features import Feature, is_enabled


class LmsCourseGate:
    """Implements `CourseGate` with `LmsWorkspace.course_access`.

    While the LMS feature is switched off nobody may open a course workspace (the
    notebook looks missing, like for a stranger).
    """

    def __init__(self, workspace: LmsWorkspace, settings: Settings) -> None:
        """Store the LMS workspace contract and the settings (feature switch)."""
        self.workspace = workspace
        self.settings = settings

    async def access(
        self, user_id: UUID, course_id: UUID
    ) -> CourseWorkspaceAccess | None:
        """Return the user's access to the course, or None."""
        if not is_enabled(self.settings, Feature.LMS):
            return None
        return await self.workspace.course_access(user_id, course_id)


class NoCourseGate:
    """A `CourseGate` for processes without the LMS: every course is closed."""

    async def access(
        self, user_id: UUID, course_id: UUID
    ) -> CourseWorkspaceAccess | None:
        """Return None (no course can be opened)."""
        return None


NO_COURSES = NoCourseGate()

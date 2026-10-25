"""Use case: change the profile, audience, enrolment and navigation settings."""

from typing import Any
from uuid import UUID

from app.modules.lms.application.authoring.access import (
    access_to,
    load_course_locked,
)
from app.modules.lms.application.authoring.draft_writer import StepDraftWriter
from app.modules.lms.application.authoring.get_course_settings import settings_view
from app.modules.lms.application.authoring.settings_views import CourseSettingsView
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.domain.authoring.course_settings import apply_settings, bad
from app.modules.lms.domain.authoring.permissions import EDIT
from app.shared.actor import Actor
from app.shared.contracts.academic import GroupDirectory
from app.shared.lms_scopes import COURSES_WRITE

FILE_FIELDS = ("cover_file_id", "banner_file_id")


class UpdateCourseDetails:
    """Apply a partial settings change under the course row lock."""

    def __init__(
        self,
        uow_factory: UowFactory,
        writer: StepDraftWriter,
        groups: GroupDirectory | None = None,
    ) -> None:
        """Store collaborators; ``groups`` validates the audience group ids."""
        self.uow_factory = uow_factory
        self.writer = writer
        self.groups = groups

    async def _require_groups(self, ids: list[str]) -> None:
        if self.groups is None or not ids:
            return
        wanted = [UUID(i) for i in ids]
        if set(wanted) - await self.groups.existing_group_ids(wanted):
            raise bad("audience_group_ids", "unknown-group")

    async def execute(
        self,
        actor: Actor,
        course_id: UUID,
        changes: dict[str, Any],
    ) -> CourseSettingsView:
        """Validate and save `changes` (last-write-wins, no lock_version)."""
        await self._require_groups(changes.get("audience_group_ids") or [])
        async with self.uow_factory() as uow:
            course = await load_course_locked(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require(EDIT)
            access.require_scope(COURSES_WRITE)
            files = {k: changes.pop(k) for k in FILE_FIELDS if k in changes}
            apply_settings(course, changes)
            wanted = [v for v in files.values() if v is not None]
            if wanted:
                await self.writer.require_files(wanted)
            for name, value in files.items():
                setattr(course, name, value)
            await uow.courses.save(course)
            await uow.commit()
            return await settings_view(uow, course)

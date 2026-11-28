"""`TeachingScope` over the teacher's current timetable."""

from uuid import UUID

from app.modules.notebooks.application.teaching_directory import TeachingDirectory
from app.shared.actor import Actor, Role


class DirectoryTeachingScope:
    """A teacher teaches the subject (and group) now; admins pass."""

    def __init__(self, directory: TeachingDirectory) -> None:
        """Bind the timetable directory."""
        self.directory = directory

    async def can_teach(
        self, actor: Actor, subject_id: UUID, group_id: UUID | None
    ) -> bool:
        """True when the actor may put material into this subject and group."""
        if actor.has(Role.ADMIN):
            return True
        if not actor.has(Role.TEACHER):
            return False
        subject = await self.directory.subject(actor.user_id, subject_id)
        if subject is None:
            return False
        return group_id is None or any(g.group_id == group_id for g in subject.groups)

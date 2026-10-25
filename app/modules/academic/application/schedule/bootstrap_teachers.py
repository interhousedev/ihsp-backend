"""Teachers named by an EMIS timetable, resolved to accounts once per import."""

from uuid import UUID

from app.shared.contracts.emis import EmisTeacher
from app.shared.contracts.identity import IdentityCommands, UserStatus

_GONE = (UserStatus.DEACTIVATED, UserStatus.DELETED)


class TeacherResolver:
    """Finds or creates each teacher through the identity module (no duplicates)."""

    def __init__(self, commands: IdentityCommands) -> None:
        """Store the identity commands; the cache lives as long as this object."""
        self._commands = commands
        self._known: dict[tuple[object, ...], UUID | None] = {}

    async def resolve(self, teacher: EmisTeacher | None) -> UUID | None:
        """Return the teacher's user id; None if EMIS names nobody or they left.

        A deactivated teacher stays unassigned: the lesson shows "teacher needed"
        until Administration picks someone (ACA-7).
        """
        if teacher is None:
            return None
        key = _key(teacher)
        if key not in self._known:
            user = await self._commands.ensure_teacher(
                emis_teacher_id=teacher.emis_id,
                first_name=teacher.first_name,
                last_name=teacher.last_name,
                middle_name=teacher.middle_name,
            )
            self._known[key] = None if user.status in _GONE else user.id
        return self._known[key]

    @property
    def count(self) -> int:
        """How many different teachers were resolved."""
        return len(self._known)


def _key(teacher: EmisTeacher) -> tuple[object, ...]:
    if teacher.emis_id is not None:
        return ("emis", teacher.emis_id)
    return ("name", teacher.last_name.casefold(), teacher.first_name.casefold())

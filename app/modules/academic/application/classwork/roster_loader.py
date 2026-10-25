"""Loads the roster of a lesson from the students of its groups."""

from collections.abc import Iterable, Sequence
from uuid import UUID

from app.modules.academic.application.classwork.people import PeopleDirectory, Person
from app.modules.academic.application.classwork.ports.unit_of_work import (
    AttendanceUnitOfWork,
)
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.domain.classwork.records import StudentRecord
from app.modules.academic.domain.classwork.roster import (
    Roster,
    RosterStudent,
    build_roster,
)


class RosterLoader:
    """Combines students (academic) and names (identity) into a Roster."""

    def __init__(self, people: PeopleDirectory) -> None:
        """Store the people directory."""
        self.people = people

    async def load(self, uow: AttendanceUnitOfWork, lesson: Lesson) -> Roster:
        """Build the roster; students saved in an earlier snapshot stay expected."""
        return await self.load_for_keys(
            uow, lesson.audience, lesson.attendance_roster or ()
        )

    async def load_for_keys(
        self,
        uow: AttendanceUnitOfWork,
        audience: Sequence[str],
        saved: Iterable[UUID] = (),
    ) -> Roster:
        """Build the roster of an audience; ``saved`` are earlier snapshot members."""
        current = await uow.students.active_in_groups(
            list(audience_keys.group_ids(audience))
        )
        known = {record.user_id for record in current}
        missing = [uid for uid in dict.fromkeys(saved) if uid not in known]
        extra = await uow.students.by_ids(missing) if missing else []
        names = await self.people.people(r.user_id for r in [*current, *extra])
        return build_roster(
            audience,
            [_student(record, names) for record in current],
            [_student(record, names) for record in extra],
        )


def _student(record: StudentRecord, names: dict[UUID, Person]) -> RosterStudent:
    person = names.get(record.user_id)
    return RosterStudent(
        user_id=record.user_id,
        first_name=person.first_name if person else "?",
        last_name=person.last_name if person else "?",
        group_id=record.group_id,
        group_name=record.group_name,
        subgroup=record.subgroup,
    )

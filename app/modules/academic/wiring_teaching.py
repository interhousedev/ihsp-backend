"""Builds the teaching services: a teacher's subject groups and their students."""

from dataclasses import dataclass

from app.modules.academic.application.teaching.get_teaching_group import (
    GetTeachingGroup,
)
from app.modules.academic.application.teaching.get_teaching_student import (
    GetTeachingStudent,
)
from app.shared.contracts.academic import (
    ClassworkQueries,
    MarksQueries,
    ScheduleQueries,
)
from app.shared.contracts.identity import IdentityDirectory
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class TeachingServices:
    """Use cases of the staff Subjects pages (read-only)."""

    get_group: GetTeachingGroup
    get_student: GetTeachingStudent


def build_teaching(
    deps: ModuleDeps,
    *,
    schedule: ScheduleQueries,
    identity: IdentityDirectory,
    marks: MarksQueries,
    classwork: ClassworkQueries,
) -> TeachingServices:
    """Wire the use cases over the academic public queries."""
    return TeachingServices(
        get_group=GetTeachingGroup(
            schedule=schedule, identity=identity, clock=deps.clock
        ),
        get_student=GetTeachingStudent(
            schedule=schedule,
            identity=identity,
            marks=marks,
            classwork=classwork,
            clock=deps.clock,
        ),
    )

"""UF-STF-06: a teacher's subject group, its students and one student's record."""

import datetime as dt
from typing import cast

from app.modules.academic.application.teaching.get_teaching_group import (
    GetTeachingGroup,
)
from app.modules.academic.application.teaching.get_teaching_student import (
    GetTeachingStudent,
)
from app.modules.academic.domain.schedule.errors import (
    NotTeachingGroupError,
    StudentNotInGroupError,
)
from app.shared.actor import Actor, Role
from app.shared.contracts.academic import (
    ClassworkQueries,
    MarkRef,
    MarksQueries,
    ScheduleQueries,
    SubjectSummary,
)
from app.shared.contracts.identity import IdentityDirectory, UserRef
from app.shared.ids import new_id
from tests.fakes.academic.teaching import (
    GROUP,
    PHYSICS,
    TODAY,
    Classwork,
    Marks,
    Schedule,
    lesson,
    student_of,
)
from tests.fakes.ai.contracts import FakeIdentity
from tests.fakes.clock import FixedClock

import pytest


@pytest.fixture
def schedule() -> Schedule:
    """The schedule fake."""
    return Schedule()


@pytest.fixture
def identity() -> FakeIdentity:
    """The identity fake."""
    return FakeIdentity()


@pytest.fixture
def teacher() -> Actor:
    """A teacher of physics to subgroup 1 of the group."""
    return Actor(user_id=new_id(), roles=frozenset({Role.TEACHER}))


@pytest.fixture
def admin() -> Actor:
    """An administrator."""
    return Actor(user_id=new_id(), roles=frozenset({Role.ADMIN}))


@pytest.fixture
def roster(schedule: Schedule, identity: FakeIdentity) -> dict[str, UserRef]:
    """Three students: one per subgroup and one without a subgroup."""
    return {
        "one": student_of(schedule, identity, "Alieva", 1),
        "two": student_of(schedule, identity, "Bakirov", 2),
        "none": student_of(schedule, identity, "Cherkasova", None),
    }


def group_use_case(schedule: Schedule, identity: FakeIdentity) -> GetTeachingGroup:
    """The group use case over the fakes."""
    return GetTeachingGroup(
        schedule=cast(ScheduleQueries, schedule),
        identity=cast(IdentityDirectory, identity),
        clock=FixedClock(),
    )


def student_use_case(
    schedule: Schedule, identity: FakeIdentity, marks: Marks, classwork: Classwork
) -> GetTeachingStudent:
    """The student use case over the fakes."""
    return GetTeachingStudent(
        schedule=cast(ScheduleQueries, schedule),
        identity=cast(IdentityDirectory, identity),
        marks=cast(MarksQueries, marks),
        classwork=cast(ClassworkQueries, classwork),
        clock=FixedClock(),
    )


async def test_subgroup_roster_and_timetable(
    schedule: Schedule,
    identity: FakeIdentity,
    teacher: Actor,
    roster: dict[str, UserRef],
) -> None:
    """UF-STF-06: a subgroup shows its students (and unassigned ones) and lessons."""
    past = lesson(TODAY - dt.timedelta(days=1), f"{GROUP}:1")
    upcoming = lesson(TODAY + dt.timedelta(days=8), f"{GROUP}:1")
    other = lesson(TODAY, f"{GROUP}:1", subject=new_id())
    schedule.teacher_lessons[teacher.user_id] = [upcoming, other, past]

    view = await group_use_case(schedule, identity).execute(teacher, PHYSICS, GROUP, 1)

    assert view.group_name == "2TN2"
    assert view.subgroup == 1
    assert view.subgroups == (1,)
    assert [s.last_name for s in view.students] == ["Alieva", "Cherkasova"]
    assert [x.id for x in view.lessons] == [past.id, upcoming.id]


async def test_whole_group_lists_everyone(
    schedule: Schedule,
    identity: FakeIdentity,
    teacher: Actor,
    roster: dict[str, UserRef],
) -> None:
    """UF-STF-06: a group taught undivided shows every student."""
    schedule.teacher_lessons[teacher.user_id] = [lesson(TODAY, str(GROUP))]

    view = await group_use_case(schedule, identity).execute(
        teacher, PHYSICS, GROUP, None
    )

    assert view.subgroups == ()
    assert len(view.students) == 3


async def test_whole_group_of_a_subgroup_teacher_hides_other_subgroup(
    schedule: Schedule,
    identity: FakeIdentity,
    teacher: Actor,
    roster: dict[str, UserRef],
) -> None:
    """UF-STF-06: a teacher of subgroup 1 never sees the students of subgroup 2."""
    schedule.teacher_lessons[teacher.user_id] = [lesson(TODAY, f"{GROUP}:1")]

    view = await group_use_case(schedule, identity).execute(
        teacher, PHYSICS, GROUP, None
    )

    assert {s.user_id for s in view.students} == {
        roster["one"].id,
        roster["none"].id,
    }


async def test_group_not_taught_is_forbidden(
    schedule: Schedule,
    identity: FakeIdentity,
    teacher: Actor,
    roster: dict[str, UserRef],
) -> None:
    """UF-STF-06: another subject, or the other subgroup, answers 403."""
    schedule.teacher_lessons[teacher.user_id] = [lesson(TODAY, f"{GROUP}:1")]
    use_case = group_use_case(schedule, identity)

    with pytest.raises(NotTeachingGroupError):
        await use_case.execute(teacher, PHYSICS, GROUP, 2)
    with pytest.raises(NotTeachingGroupError):
        await use_case.execute(teacher, new_id(), GROUP, None)


async def test_admin_sees_any_group(
    schedule: Schedule,
    identity: FakeIdentity,
    admin: Actor,
    roster: dict[str, UserRef],
) -> None:
    """UF-STF-06: Administration sees the group and its lessons of the subject."""
    schedule.student_lessons = [lesson(TODAY, f"{GROUP}:2")]

    view = await group_use_case(schedule, identity).execute(admin, PHYSICS, GROUP, 2)

    assert [s.user_id for s in view.students] == [roster["two"].id, roster["none"].id]
    assert len(view.lessons) == 1


def mark(value: int, semester: int = 1) -> MarkRef:
    """A physics lesson mark."""
    return MarkRef(
        subject_id=PHYSICS,
        subject_name="Physics",
        semester=semester,
        type="lesson",
        value=value,
        date=TODAY,
        lesson_id=None,
    )


async def test_student_record(
    schedule: Schedule,
    identity: FakeIdentity,
    teacher: Actor,
    roster: dict[str, UserRef],
) -> None:
    """UF-STF-06: marks of the newest semester, their average, homework, absences."""
    taught = lesson(TODAY, f"{GROUP}:1", teacher=teacher.user_id)
    schedule.teacher_lessons[teacher.user_id] = [taught]
    marks, classwork = Marks(), Classwork()
    marks.rows = [mark(2, 1), mark(5, 2), mark(4, 2)]
    marks.summary = [
        SubjectSummary(PHYSICS, "Physics", (), 4.5, None, 1, 10),
        SubjectSummary(new_id(), "Maths", (), None, None, 3, 9),
    ]
    stamp = dt.datetime(2026, 10, 5, 12, tzinfo=dt.UTC)
    classwork.homework_items = [
        {"lesson": taught, "done_at": stamp, "note": "photo in Drive"},
        {"lesson": lesson(TODAY, str(GROUP), subject=new_id()), "done_at": None},
    ]
    classwork.absence_items = [{"lesson": taught, "excused": True}]
    use_case = student_use_case(schedule, identity, marks, classwork)

    view = await use_case.execute(teacher, PHYSICS, GROUP, roster["one"].id, 1)

    assert view.student.last_name == "Alieva"
    assert [m.value for m in view.marks] == [5, 4]
    assert view.average == 4.5
    assert view.semester_mark == 4.5
    assert [h.lesson_id for h in view.homework] == [taught.id]
    assert view.homework[0].note == "photo in Drive"
    assert view.absences == 1
    assert view.lessons_with_attendance == 10
    assert view.absent_lessons[0].excused is True


async def test_student_of_other_subgroup_is_not_found(
    schedule: Schedule,
    identity: FakeIdentity,
    teacher: Actor,
    roster: dict[str, UserRef],
) -> None:
    """UF-STF-06: a student outside the taught subgroup is not shown."""
    schedule.teacher_lessons[teacher.user_id] = [lesson(TODAY, f"{GROUP}:1")]
    use_case = student_use_case(schedule, identity, Marks(), Classwork())

    with pytest.raises(StudentNotInGroupError):
        await use_case.execute(teacher, PHYSICS, GROUP, roster["two"].id, None)


async def test_student_of_untaught_group_is_forbidden(
    schedule: Schedule,
    identity: FakeIdentity,
    teacher: Actor,
    roster: dict[str, UserRef],
) -> None:
    """UF-STF-06: a teacher who does not teach the group gets 403."""
    use_case = student_use_case(schedule, identity, Marks(), Classwork())

    with pytest.raises(NotTeachingGroupError):
        await use_case.execute(teacher, PHYSICS, GROUP, roster["one"].id, None)


async def test_student_without_marks_has_no_average(
    schedule: Schedule,
    identity: FakeIdentity,
    admin: Actor,
    roster: dict[str, UserRef],
) -> None:
    """UF-STF-06: Administration sees any student; no marks means no average."""
    use_case = student_use_case(schedule, identity, Marks(), Classwork())

    view = await use_case.execute(admin, PHYSICS, GROUP, roster["two"].id, None)

    assert view.average is None
    assert view.marks == []
    assert view.lessons_with_attendance is None

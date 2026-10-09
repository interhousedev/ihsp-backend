"""ACA-1, ACA-4, ACA-5, ACA-7, ID-10: a group is filled from the fake EMIS, end to end.

The whole `all` container runs over the test database and the fake EMIS (30 students,
two groups, five bells). Tasks are not run by a broker here: the test runs the use
case behind each kicked task, in the order a worker would.
"""

import datetime as dt
from uuid import UUID

import app.modules.identity.infrastructure.emis.fake as fake_emis
from app.bootstrap.container import Container
from app.modules.academic.application.schedule.results import TermData
from app.modules.academic.application.schedule.sync_group_timetable import (
    TimetableResult,
)
from app.modules.academic.domain.schedule.term import Bell
from app.modules.identity.infrastructure.emis.fake import (
    FAKE_CLASS_HOURS,
    FAKE_PASSWORD,
)
from app.shared.actor import SYSTEM_ACTOR, Role
from app.shared.clock import TASHKENT
from app.shared.contracts.academic import LessonRef
from app.shared.contracts.emis import EmisClassHour
from app.shared.contracts.identity import UserRef, UserStatus
from tests.integration.conftest import ContainerFactory, IntegrationWorld

import pytest

TERM_START = dt.date(2026, 9, 2)
TERM_END = dt.date(2026, 12, 30)
OLD_BELLS = [
    Bell(
        period=1, start=dt.time(8, 30), end=dt.time(9, 15), weekdays=[1, 2, 3, 4, 5, 6]
    ),
    Bell(
        period=2, start=dt.time(9, 25), end=dt.time(10, 10), weekdays=[1, 2, 3, 4, 5, 6]
    ),
]
EMIS_STARTS = {hour.begin_time for hour in FAKE_CLASS_HOURS}
TODAY = dt.date(2026, 10, 6)  # the test clock's day
WINDOW_END = dt.date(2026, 11, 1)  # the Sunday of the fourth week
LESSON_LENGTH = dt.timedelta(minutes=80)


async def make_term(container: Container) -> TermData:
    """A term around the test clock's day with the old 45-minute bells."""
    return await container.academic.schedule.create_term.execute(
        academic_year="2026-2027",
        half=1,
        starts_on=TERM_START,
        ends_on=TERM_END,
        bells=OLD_BELLS,
        non_study_days=[],
        moved_days=[],
    )


async def register(container: Container, world: IntegrationWorld, login: str) -> UUID:
    """Register one fake EMIS student and return the user id."""
    emis = container.identity.emis
    started = await emis.register_start.execute(
        emis_login=login, emis_password=FAKE_PASSWORD, ip=None, locale="ru"
    )
    await emis.register_email_code.execute(
        registration_token=started.registration_token, email=f"{login}@ihsu.uz"
    )
    registered = await emis.register_complete.execute(
        registration_token=started.registration_token,
        password="StudentDemo1",
        email_code=world.email.last_code or "",
        confirm_import_match=True,
        login_challenge=None,
        ip=None,
        user_agent=None,
    )
    return registered.user_id


def kicked(world: IntegrationWorld, task: str) -> list[dict[str, object]]:
    return [kwargs for name, kwargs in world.kicker.calls if name == task]


async def teachers(container: Container) -> list[UserRef]:
    async with container.identity.auth.uow_factory() as uow:
        users = await uow.users.list_with_roles([Role.TEACHER])
    return [user.to_ref() for user in users]


async def group_entries(container: Container, term: TermData, group_id: UUID) -> int:
    entries = await container.academic.schedule.list_entries.execute(
        SYSTEM_ACTOR, term_id=term.id, group_id=group_id
    )
    return len(entries)


async def lessons_of(container: Container, user_id: UUID) -> list[LessonRef]:
    """The student's lessons from the test day to the end of the four-week window."""
    return await container.academic.schedule.queries.lessons_for_student(
        user_id, TODAY, WINDOW_END
    )


async def sync(container: Container, task: dict[str, object]) -> TimetableResult:
    """Run the use case behind a kicked `academic.sync_group_timetable`."""
    return await container.academic.emis_import.sync_group_timetable.execute(
        group_id=UUID(str(task["group_id"])), user_id=UUID(str(task["user_id"]))
    )


async def test_registering_a_student_fills_the_group_with_a_timetable_from_emis(
    make_container: ContainerFactory, world: IntegrationWorld
) -> None:
    """ACA-1, ACA-5, ACA-7: entries with parity, teachers, lessons with EMIS times."""
    container = await make_container("all")
    term = await make_term(container)

    user_id = await register(container, world, "student01")

    [task] = kicked(world, "academic.sync_group_timetable")
    assert task["user_id"] == str(user_id)
    group_id = UUID(str(task["group_id"]))
    assert await group_entries(container, term, group_id) == 0  # registration is fast

    result = await sync(container, task)

    assert result.status == "synced" and result.entries > 0 and result.skipped == 0
    assert result.subgroup == 1  # student01 is in the first half
    entries = await container.academic.schedule.list_entries.execute(
        SYSTEM_ACTOR, term_id=term.id, group_id=group_id
    )
    assert {e.source for e in entries} == {"emis"}
    saturdays = [e for e in entries if e.weekday == 6]
    assert sorted(e.week_parity for e in saturdays) == ["even", "odd"]
    assert {a.subgroup for e in entries for a in e.audience} == {None, 1}
    made = await teachers(container)
    assert {t.last_name for t in made} == {
        "Kalandarova",
        "Yuldashev",
        "Ismoilova",
        "Nazarov",
        "Rahimov",
    }
    assert {t.status for t in made} == {UserStatus.PENDING_ACTIVATION}
    lessons = await lessons_of(container, user_id)
    assert {x.starts_at.astimezone(TASHKENT).time() for x in lessons} <= EMIS_STARTS
    assert {x.ends_at - x.starts_at for x in lessons} == {LESSON_LENGTH}
    odd = {x.date for x in lessons if x.date.isoweekday() == 6}
    assert odd == {
        dt.date(2026, 10, 10),
        dt.date(2026, 10, 17),
        dt.date(2026, 10, 24),
        dt.date(2026, 10, 31),
    }
    [stored] = await container.academic.schedule.list_terms.execute()
    assert {b.source for b in stored.bells} == {"emis"}


async def test_exam_weeks_arrive_but_emis_materials_do_not(
    make_container: ContainerFactory, world: IntegrationWorld
) -> None:
    """ACA-7: the kind (midterm) is imported; topics, files and videos are not."""
    container = await make_container("all")
    await make_term(container)
    user_id = await register(container, world, "student01")
    [task] = kicked(world, "academic.sync_group_timetable")
    group_id = UUID(str(task["group_id"]))

    result = await sync(container, task)

    lessons = await lessons_of(container, user_id)
    [midterm] = [x for x in lessons if x.kind == "midterm"]
    assert midterm.date == dt.date(2026, 10, 20)
    controls = await container.academic.schedule.queries.emis_control_lessons(
        [group_id], TODAY, WINDOW_END
    )
    assert [x.id for x in controls] == [midterm.id]
    assert all(x.topic is None and x.topic_source is None for x in lessons)
    assert result.resources == 0
    for lesson in lessons:
        assert await container.links.public.lesson_resources(lesson.id) == []


async def test_the_other_half_and_a_second_run_change_nothing_they_should_not(
    make_container: ContainerFactory, world: IntegrationWorld
) -> None:
    """ACA-1, ACA-2: each half comes from its own student; re-runs are no-ops."""
    container = await make_container("all")
    term = await make_term(container)
    first = await register(container, world, "student01")
    second = await register(container, world, "student02")
    first_task, second_task = kicked(world, "academic.sync_group_timetable")
    group_id = UUID(str(first_task["group_id"]))
    assert second_task["group_id"] == first_task["group_id"]

    await sync(container, first_task)
    half_one = await group_entries(container, term, group_id)
    done = await sync(container, second_task)
    both = await group_entries(container, term, group_id)
    people = len(await teachers(container))
    lessons = len(await lessons_of(container, first))
    again_first = await sync(container, first_task)
    again_second = await sync(container, second_task)

    assert done.subgroup == 2 and both > half_one
    assert (again_first.entries, again_first.removed, again_first.updated) == (0, 0, 0)
    assert (again_second.entries, again_second.removed, again_second.updated) == (
        0,
        0,
        0,
    )
    assert await group_entries(container, term, group_id) == both
    assert len(await teachers(container)) == people
    assert len(await lessons_of(container, first)) == lessons
    own = await container.academic.schedule.queries.lessons_for_student(
        second, TODAY, WINDOW_END
    )
    assert {a.rsplit(":", 1)[-1] for x in own for a in x.audience if ":" in a} == {"2"}


async def test_a_second_group_reuses_the_teachers_of_the_first(
    make_container: ContainerFactory, world: IntegrationWorld
) -> None:
    """ACA-1, ACA-6: teachers are matched by EMIS id, so they are created once."""
    container = await make_container("all")
    await make_term(container)
    await register(container, world, "student01")
    await register(container, world, "student16")  # group 1TN1
    for task in kicked(world, "academic.sync_group_timetable"):
        result = await sync(container, task)
        assert (result.status, result.merged, result.skipped) == ("synced", 0, 0)

    assert len(await teachers(container)) == 5


async def test_the_evening_run_moves_future_lessons_when_emis_changes_the_bells(
    make_container: ContainerFactory,
    world: IntegrationWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ACA-4, ACA-7: the 20:00 run also refreshes the timetables of the groups."""
    container = await make_container("all")
    await make_term(container)
    user_id = await register(container, world, "student01")
    [task] = kicked(world, "academic.sync_group_timetable")
    await sync(container, task)
    await container.academic.marks.backfill_student.execute(user_id)
    before = await lessons_of(container, user_id)
    moved = (EmisClassHour(0, dt.time(8, 40), dt.time(10, 0)), *FAKE_CLASS_HOURS[1:])
    monkeypatch.setattr(fake_emis, "FAKE_CLASS_HOURS", moved)

    await container.academic.marks.sync_all.execute("20:00")

    after = await lessons_of(container, user_id)
    now = world.clock.now()
    assert [x.starts_at for x in after if x.starts_at <= now] == [
        x.starts_at for x in before if x.starts_at <= now
    ]  # lessons that started keep their times
    future = {
        x.starts_at.astimezone(TASHKENT).time() for x in after if x.starts_at > now
    }
    assert dt.time(8, 40) in future and dt.time(8, 30) not in future
    assert {x.ends_at - x.starts_at for x in after} == {LESSON_LENGTH}
    assert [x.id for x in after] == [x.id for x in before]  # none made, none lost

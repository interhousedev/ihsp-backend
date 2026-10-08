"""ACA-1, ACA-4, ACA-7, ID-10: an unknown group is filled from the fake EMIS.

The whole `all` container runs over the test database and the fake EMIS (30 students,
two groups, five bells). Tasks are not run by a broker here: the test runs the use
case behind each kicked task, in the order a worker would.
"""

import datetime as dt
from uuid import UUID

import app.modules.identity.infrastructure.emis.fake as fake_emis
from app.bootstrap.container import Container
from app.modules.academic.application.schedule.results import TermData
from app.modules.academic.domain.schedule.term import Bell
from app.modules.identity.infrastructure.emis.fake import (
    FAKE_CLASS_HOURS,
    FAKE_PASSWORD,
    FakeEmisClient,
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
    """The student's generated lessons from the test day to two weeks ahead."""
    return await container.academic.schedule.queries.lessons_for_student(
        user_id, dt.date(2026, 10, 6), dt.date(2026, 10, 20)
    )


async def test_registering_a_student_of_an_unknown_group_imports_the_whole_group(
    make_container: ContainerFactory, world: IntegrationWorld
) -> None:
    """ACA-1: group, teachers, entries and lessons, with the EMIS bell times."""
    container = await make_container("all")
    term = await make_term(container)

    user_id = await register(container, world, "student01")

    [task] = kicked(world, "academic.bootstrap_group")
    assert task["user_id"] == str(user_id)
    assert kicked(world, "academic.sync_class_hours") == []
    group_id = UUID(str(task["group_id"]))
    assert await group_entries(container, term, group_id) == 0  # registration is fast

    result = await container.academic.emis_import.bootstrap_group.execute(
        group_id=group_id, user_id=user_id
    )

    expected = await FakeEmisClient(world.clock).timetable("fake-token:student01")
    assert result.status == "imported"
    assert (result.entries, result.merged, result.skipped) == (len(expected), 0, 0)
    assert await group_entries(container, term, group_id) == len(expected)
    made = await teachers(container)
    assert {t.last_name for t in made} == {
        "Kalandarova",
        "Yuldashev",
        "Ismoilova",
        "Nazarov",
        "Rahimov",
    }
    assert {t.status for t in made} == {UserStatus.PENDING_ACTIVATION}
    assert all(t.login and "." in t.login for t in made)
    lessons = await lessons_of(container, user_id)
    assert lessons
    assert {x.starts_at.astimezone(TASHKENT).time() for x in lessons} <= EMIS_STARTS
    assert {x.ends_at - x.starts_at for x in lessons} == {LESSON_LENGTH}
    [stored] = await container.academic.schedule.list_terms.execute()
    assert {b.source for b in stored.bells} == {"emis"}


async def test_a_second_student_of_the_group_adds_nothing(
    make_container: ContainerFactory, world: IntegrationWorld
) -> None:
    """ACA-1: no duplicate entries, lessons or teachers."""
    container = await make_container("all")
    term = await make_term(container)
    first = await register(container, world, "student01")
    [task] = kicked(world, "academic.bootstrap_group")
    group_id = UUID(str(task["group_id"]))
    await container.academic.emis_import.bootstrap_group.execute(
        group_id=group_id, user_id=first
    )
    entries = await group_entries(container, term, group_id)
    people = len(await teachers(container))
    lessons = len(await lessons_of(container, first))

    second = await register(container, world, "student02")

    assert len(kicked(world, "academic.bootstrap_group")) == 1  # none for student02
    assert len(kicked(world, "academic.sync_class_hours")) == 1
    again = await container.academic.emis_import.bootstrap_group.execute(
        group_id=group_id, user_id=second
    )
    synced = await container.academic.emis_import.sync_class_hours.execute(second)
    assert (again.status, synced.status) == ("exists", "unchanged")
    assert await group_entries(container, term, group_id) == entries
    assert len(await teachers(container)) == people
    assert len(await lessons_of(container, second)) == lessons


async def test_a_second_group_reuses_the_teachers_of_the_first(
    make_container: ContainerFactory, world: IntegrationWorld
) -> None:
    """ACA-1: teachers are matched by EMIS id, so they are created once."""
    container = await make_container("all")
    await make_term(container)
    first = await register(container, world, "student01")
    second = await register(container, world, "student16")  # group 1TN1
    for user_id, task in zip(
        (first, second), kicked(world, "academic.bootstrap_group"), strict=True
    ):
        result = await container.academic.emis_import.bootstrap_group.execute(
            group_id=UUID(str(task["group_id"])), user_id=user_id
        )
        assert (result.status, result.merged, result.skipped) == ("imported", 0, 0)

    assert len(await teachers(container)) == 5


async def test_the_evening_sync_moves_future_lessons_when_emis_changes_the_bells(
    make_container: ContainerFactory,
    world: IntegrationWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ACA-4, ACA-7: only when they differ; past lessons keep their times."""
    container = await make_container("all")
    await make_term(container)
    user_id = await register(container, world, "student01")
    [task] = kicked(world, "academic.bootstrap_group")
    await container.academic.emis_import.bootstrap_group.execute(
        group_id=UUID(str(task["group_id"])), user_id=user_id
    )
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
    assert len(after) == len(before)

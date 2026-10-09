"""ACA-7, ACA-9: with EMIS__IMPORT_TOPICS on, topics and files arrive, labelled "emis".

The setting is off by default (EMIS materials are unreliable), so the default path is
tested in test_emis_group_bootstrap.py; this module builds the container with it on.
"""

import datetime as dt
from collections.abc import AsyncIterator
from uuid import UUID

from app.bootstrap.common import BuildOverrides, build_container
from app.bootstrap.container import Container
from app.modules.academic.application.schedule.results import TermData
from app.modules.academic.application.schedule.sync_group_timetable import (
    TimetableResult,
)
from app.modules.academic.domain.schedule.term import Bell
from app.modules.identity.infrastructure.emis.fake import FAKE_PASSWORD, FakeEmisClient
from app.settings import Settings
from app.shared.contracts.academic import LessonRef
from tests.integration.conftest import ContainerFactory, IntegrationWorld

import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncEngine

TODAY = dt.date(2026, 10, 6)
WINDOW_END = dt.date(2026, 11, 1)
TERM_START = dt.date(2026, 9, 2)
TERM_END = dt.date(2026, 12, 30)
OLD_BELLS = [
    Bell(
        period=1, start=dt.time(8, 30), end=dt.time(9, 15), weekdays=[1, 2, 3, 4, 5, 6]
    ),
]


@pytest_asyncio.fixture
async def make_container(
    settings: Settings, redis: FakeRedis, world: IntegrationWorld, engine: AsyncEngine
) -> AsyncIterator[ContainerFactory]:
    """Like the shared `make_container`, with EMIS__IMPORT_TOPICS switched on."""
    emis = settings.emis.model_copy(update={"import_topics": True})
    used = settings.model_copy(update={"emis": emis})
    built: list[Container] = []

    async def factory(process: str) -> Container:
        container = await build_container(
            used,
            process=process,
            kicker=world.kicker,
            overrides=BuildOverrides(
                clock=world.clock,
                redis=redis,
                credentials=world.credentials,
                email_sender=world.email,
            ),
        )
        built.append(container)
        return container

    assert engine is not None  # the test database must exist first
    try:
        yield factory
    finally:
        for container in built:
            await container.close()


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


async def lessons_of(container: Container, user_id: UUID) -> list[LessonRef]:
    return await container.academic.schedule.queries.lessons_for_student(
        user_id, TODAY, WINDOW_END
    )


async def sync(container: Container, task: dict[str, object]) -> TimetableResult:
    return await container.academic.emis_import.sync_group_timetable.execute(
        group_id=UUID(str(task["group_id"])), user_id=UUID(str(task["user_id"]))
    )


async def test_topics_and_resources_arrive_labelled_as_emis_when_switched_on(
    make_container: ContainerFactory, world: IntegrationWorld
) -> None:
    """ACA-7, ACA-9: the EMIS topic and its files are labelled "emis"."""
    container = await make_container("all")
    await make_term(container)
    user_id = await register(container, world, "student01")
    [task] = kicked(world, "academic.sync_group_timetable")

    await sync(container, task)

    lessons = await lessons_of(container, user_id)
    todays = [x for x in lessons if x.date == TODAY]
    assert todays and all(x.topic_source == "emis" for x in todays)
    assert all(x.topic is None for x in lessons if x.date > TODAY)
    expected = await _expected_urls(world, todays)
    attached = {}
    for lesson in todays:
        refs = await container.links.public.lesson_resources(lesson.id)
        attached[lesson.id] = {r.title for r in refs}
        assert {r.source for r in refs} <= {"emis"}
        assert {r.author_first_name for r in refs} <= {"EMIS"}
    assert attached == expected
    assert any(attached.values())
    # the second run attaches nothing new
    again = await sync(container, task)
    assert again.resources == 0


async def _expected_urls(
    world: IntegrationWorld, todays: list[LessonRef]
) -> dict[UUID, set[str]]:
    """The titles the fake's topics of today imply, per lesson."""
    fake = FakeEmisClient(world.clock)
    token = await fake.login("student01", FAKE_PASSWORD)
    classes = await fake.timetable(token, TODAY, TODAY)
    titles: dict[UUID, set[str]] = {}
    for lesson in todays:
        titles[lesson.id] = set()
        for item in classes:
            if item.pair_number + 1 != lesson.period or item.topic is None:
                continue
            topic = item.topic
            if topic.topic_file_url:
                titles[lesson.id].add(topic.name)
            if topic.homework_file_url:
                titles[lesson.id].add(f"{topic.name} (homework)")
            if topic.video_url:
                titles[lesson.id].add(f"{topic.name} (video)")
    return titles

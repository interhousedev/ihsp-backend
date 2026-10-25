"""ACA-9: EMIS materials of the whole term on the first sync, and the admin re-sync."""

from types import TracebackType
from typing import Self
from uuid import UUID

from app.modules.academic.application.marks.resync_materials import ResyncMaterials
from app.modules.academic.domain.schedule.fetchers import pick_fetchers
from app.shared.contracts.emis import EmisTopic
from app.shared.ids import new_id
from tests.academic.marks.fakes.timetable_sync import FakeTimetableSync
from tests.academic.schedule.emis_builders import day, klass, weekly
from tests.academic.schedule.env import Env

FILE = "https://cdn-emis.edu.uz/files/a.pdf"
HOMEWORK = "https://cdn-emis.edu.uz/files/b.pdf"
THIS_TERM = ("2026-2027", 1)


def files_topic() -> EmisTopic:
    return EmisTopic(name="Jadids", topic_file_url=FILE, homework_file_url=HOMEWORK)


async def set_up(env: Env) -> tuple[UUID, UUID]:
    await env.term()
    group = await env.group("2TN2", emis_group_id=3292)
    user = await env.student(group)
    return group.id, user.id


async def lesson_id_on(env: Env, when: object) -> UUID:
    found = [x.id for x in await env.lessons() if x.date == when and x.period == 1]
    assert len(found) == 1, found
    return found[0]


async def test_the_first_sync_imports_materials_from_the_term_start(
    topics_env: Env,
) -> None:
    """A class of September (before the fetched weeks) gets its materials too."""
    env = topics_env
    group_id, user_id = await set_up(env)
    early = day(-4, 2)  # 8 September, term week 2
    env.emis.classes = [klass(-4, 2, topic=files_topic()), *weekly(2, 0)]

    result = await env.emis_import.sync_group_timetable.execute(
        group_id=group_id, user_id=user_id, full_term=True
    )

    attached = env.urls.of(await lesson_id_on(env, early))
    assert [(a.url, a.kind) for a in attached] == [
        (FILE, "classwork"),
        (HOMEWORK, "homework"),
    ]
    assert result.resources == 2
    assert set(env.urls.readers) == {user_id}


async def test_a_later_sync_does_not_read_the_earlier_weeks(topics_env: Env) -> None:
    """Only the first sync of a group goes back to the term start."""
    env = topics_env
    group_id, user_id = await set_up(env)
    env.emis.classes = weekly(2, 0)
    await env.emis_import.sync_group_timetable.execute(
        group_id=group_id, user_id=user_id
    )
    env.emis.classes = [klass(-4, 2, topic=files_topic()), *weekly(2, 0)]

    await env.emis_import.sync_group_timetable.execute(
        group_id=group_id, user_id=user_id
    )

    assert env.urls.of(await lesson_id_on(env, day(-4, 2))) == []


async def test_resync_replaces_the_materials_of_the_chosen_term(
    topics_env: Env,
) -> None:
    """The group's EMIS materials are purged, then imported fresh."""
    env = topics_env
    group_id, user_id = await set_up(env)
    env.emis.classes = [klass(-4, 2, topic=files_topic()), *weekly(2, 0)]
    await env.emis_import.sync_group_timetable.execute(
        group_id=group_id, user_id=user_id, full_term=True
    )
    early = await lesson_id_on(env, day(-4, 2))

    added = await env.emis_import.sync_group_timetable.resync_materials(
        group_id=group_id, terms={THIS_TERM}, fetchers=[[user_id]]
    )

    assert early in env.urls.purged
    assert added == 2
    assert len(env.urls.of(early)) == 2


async def test_resync_skips_terms_that_were_not_chosen(topics_env: Env) -> None:
    """Term filter: another year leaves the materials and EMIS alone."""
    env = topics_env
    group_id, user_id = await set_up(env)
    env.emis.classes = weekly(2, 0, topic=files_topic())
    await env.emis_import.sync_group_timetable.execute(
        group_id=group_id, user_id=user_id
    )
    calls = len(env.emis.calls)

    added = await env.emis_import.sync_group_timetable.resync_materials(
        group_id=group_id, terms={("2025-2026", 2)}, fetchers=[[user_id]]
    )

    assert added == 0
    assert env.urls.purged == []
    assert len(env.emis.calls) == calls


async def test_resync_deletes_nothing_when_emis_cannot_be_read(
    topics_env: Env,
) -> None:
    """Every fetcher failing keeps the old materials."""
    env = topics_env
    group_id, user_id = await set_up(env)
    env.emis.classes = weekly(2, 0, topic=files_topic())
    await env.emis_import.sync_group_timetable.execute(
        group_id=group_id, user_id=user_id
    )
    before = dict(env.urls.attached)
    env.emis.down()

    await env.emis_import.sync_group_timetable.resync_materials(
        group_id=group_id, terms={THIS_TERM}, fetchers=[[user_id]]
    )

    assert env.urls.purged == []
    assert env.urls.attached == before


# - - - two students per group - - -


def test_a_split_group_reads_one_student_of_each_half() -> None:
    """Half 1 and half 2 each give a fetcher; students of no half are not asked."""
    a, b, c, d = (new_id() for _ in range(4))

    slots = pick_fetchers([(a, None), (b, 1), (c, 2), (d, 1)])

    assert slots == [[b, d], [c]]


def test_an_unsplit_group_reads_any_two_students() -> None:
    """Two disjoint fetchers, each with stand-ins."""
    ids = [new_id() for _ in range(5)]

    slots = pick_fetchers([(i, None) for i in ids])

    assert slots == [[ids[0], ids[2], ids[4]], [ids[1], ids[3]]]
    assert pick_fetchers([(ids[0], 1)]) == [[ids[0]]]


class _Students:
    def __init__(self, members: list[tuple[UUID, UUID, int | None]]) -> None:
        self.members = members

    async def list_sync_members(self) -> list[tuple[UUID, UUID, int | None]]:
        return self.members


class _Uow:
    def __init__(self, members: list[tuple[UUID, UUID, int | None]]) -> None:
        self.students = _Students(members)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


async def test_resync_asks_each_group_through_two_students() -> None:
    """The worker run picks the fetchers per group and passes the terms on."""
    split, whole = new_id(), new_id()
    s1, s2, s3, w1, w2, w3 = (new_id() for _ in range(6))
    members = [
        (s1, split, 1),
        (s2, split, 2),
        (s3, split, 1),
        (w1, whole, None),
        (w2, whole, None),
        (w3, whole, None),
    ]
    sync = FakeTimetableSync()
    use_case = ResyncMaterials(
        uow_factory=lambda: _Uow(members),  # type: ignore[arg-type,return-value]
        materials=sync,
    )

    await use_case.execute([THIS_TERM])

    by_group = {group: (terms, slots) for group, terms, slots in sync.resyncs}
    assert by_group[split] == (frozenset({THIS_TERM}), [[s1, s3], [s2]])
    assert by_group[whole] == (frozenset({THIS_TERM}), [[w1, w3], [w2]])

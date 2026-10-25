"""Admin EMIS pull of one subject: full or soft, by teacher or by group."""

from types import SimpleNamespace, TracebackType
from typing import Any, Self
from uuid import UUID

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_schedule import ROUTERS as ADMIN_ROUTERS
from app.modules.academic.application.marks.resync_materials import ResyncMaterials
from app.modules.academic.domain.schedule.lesson import Lesson
from app.modules.academic.domain.schedule.material_scope import MaterialScope
from app.shared.actor import Actor, Role
from app.shared.contracts.emis import EmisTopic
from app.shared.ids import new_id
from tests.academic.marks.fakes.timetable_sync import FakeTimetableSync
from tests.academic.schedule.emis_builders import (
    PHYSICS,
    YULDASHEV,
    day,
    klass,
    weekly,
)
from tests.academic.schedule.env import Env
from tests.conftest import HttpClientFactory
from tests.factories import make_actor

THIS_TERM = ("2026-2027", 1)


def topic(url: str) -> EmisTopic:
    return EmisTopic(name="T", topic_file_url=url)


async def set_up(env: Env) -> tuple[UUID, UUID]:
    await env.term()
    group = await env.group("2TN2", emis_group_id=3292)
    user = await env.student(group)
    return group.id, user.id


async def lesson_on(env: Env, when: object, period: int = 1) -> Lesson:
    found = [x for x in await env.lessons() if x.date == when and x.period == period]
    assert len(found) == 1, found
    return found[0]


async def first_sync(env: Env, group_id: UUID, user_id: UUID) -> None:
    await env.emis_import.sync_group_timetable.execute(
        group_id=group_id, user_id=user_id, full_term=True
    )


async def test_full_pull_replaces_only_the_subjects_lessons(topics_env: Env) -> None:
    env = topics_env
    group_id, user_id = await set_up(env)
    env.emis.classes = [
        klass(-4, 2, topic=topic("https://e/m.pdf")),
        klass(-4, 2, 1, subject=PHYSICS, topic=topic("https://e/p.pdf")),
        *weekly(2, 0),
        *weekly(2, 1, subject=PHYSICS),
    ]
    await first_sync(env, group_id, user_id)
    math, physics = await lesson_on(env, day(-4, 2)), await lesson_on(
        env, day(-4, 2), 2
    )

    added = await env.emis_import.sync_group_timetable.resync_materials(
        group_id=group_id,
        terms={THIS_TERM},
        fetchers=[[user_id]],
        scope=MaterialScope(subject_id=physics.subject_id),
    )

    assert physics.id in env.urls.purged and math.id not in env.urls.purged
    assert added == 1
    assert len(env.urls.of(math.id)) == 1


async def test_soft_pull_fills_empty_lessons_and_deletes_nothing(
    topics_env: Env,
) -> None:
    env = topics_env
    group_id, user_id = await set_up(env)
    env.emis.classes = [
        klass(-4, 2, topic=topic("https://e/m1.pdf")),
        klass(-4, 2, 1, subject=PHYSICS),
        *weekly(2, 0),
        *weekly(2, 1, subject=PHYSICS),
    ]
    await first_sync(env, group_id, user_id)
    math, physics = await lesson_on(env, day(-4, 2)), await lesson_on(
        env, day(-4, 2), 2
    )
    env.emis.classes = [
        klass(-4, 2, topic=topic("https://e/m2.pdf")),
        klass(-4, 2, 1, subject=PHYSICS, topic=topic("https://e/p.pdf")),
        *weekly(2, 0),
        *weekly(2, 1, subject=PHYSICS),
    ]

    for subject_id in (math.subject_id, physics.subject_id):
        await env.emis_import.sync_group_timetable.resync_materials(
            group_id=group_id,
            terms=None,  # the current term
            fetchers=[[user_id]],
            scope=MaterialScope(subject_id=subject_id, mode="soft"),
        )

    assert env.urls.purged == []
    assert [m.url for m in env.urls.of(math.id)] == ["https://e/m1.pdf"]
    assert [m.url for m in env.urls.of(physics.id)] == ["https://e/p.pdf"]


async def test_a_teacher_scope_touches_only_that_teachers_lessons(
    topics_env: Env,
) -> None:
    env = topics_env
    group_id, user_id = await set_up(env)
    env.emis.classes = [
        klass(-4, 2, topic=topic("https://e/a.pdf")),
        klass(-4, 2, 1, teacher=YULDASHEV, topic=topic("https://e/b.pdf")),
        *weekly(2, 0),
        *weekly(2, 1, teacher=YULDASHEV),
    ]
    await first_sync(env, group_id, user_id)
    mine, other = await lesson_on(env, day(-4, 2), 2), await lesson_on(env, day(-4, 2))
    assert mine.teacher_id != other.teacher_id

    await env.emis_import.sync_group_timetable.resync_materials(
        group_id=group_id,
        terms={THIS_TERM},
        fetchers=[[user_id]],
        scope=MaterialScope(subject_id=mine.subject_id, teacher_id=mine.teacher_id),
    )

    assert mine.id in env.urls.purged and other.id not in env.urls.purged


async def test_a_group_without_the_subject_does_not_ask_emis(
    topics_env: Env,
) -> None:
    env = topics_env
    group_id, user_id = await set_up(env)
    env.emis.classes = weekly(2, 0, topic=topic("https://e/a.pdf"))
    await first_sync(env, group_id, user_id)
    calls = len(env.emis.calls)

    added = await env.emis_import.sync_group_timetable.resync_materials(
        group_id=group_id,
        terms={THIS_TERM},
        fetchers=[[user_id]],
        scope=MaterialScope(subject_id=new_id()),
    )

    assert added == 0 and env.urls.purged == []
    assert len(env.emis.calls) == calls


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


async def test_a_group_filter_reads_only_that_group() -> None:
    one, two = new_id(), new_id()
    a, b, c = new_id(), new_id(), new_id()
    sync = FakeTimetableSync()
    scope = MaterialScope(subject_id=new_id(), mode="soft")
    use_case = ResyncMaterials(
        uow_factory=lambda: _Uow(  # type: ignore[arg-type,return-value]
            [(a, one, None), (b, one, None), (c, two, None)]
        ),
        materials=sync,
    )

    await use_case.execute(None, scope=scope, group_id=two)

    assert [group for group, _, _ in sync.resyncs] == [two]
    assert sync.resyncs[0][2] == [[c]]
    assert sync.scopes == [scope]


# - - - HTTP - - -


class _FakeManualSync:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def pull_subject(self, actor: Actor, subject_id: UUID, **kw: Any) -> None:
        actor.require(Role.ADMIN)
        assert kw.pop("job_id")
        self.calls.append({"subject_id": subject_id, **kw})


async def _client(
    env: Env, http_client: HttpClientFactory, role: Role
) -> tuple[Any, _FakeManualSync]:
    manual = _FakeManualSync()
    actor = make_actor(role)
    client = await http_client(
        ADMIN_ROUTERS,
        {get_actor: lambda: actor},
        academic=SimpleNamespace(
            schedule=env.services,
            marks=SimpleNamespace(run_manual_sync=manual),
        ),
    )
    return client, manual


async def test_emis_pull_answers_202_and_passes_the_filters(
    env: Env, http_client: HttpClientFactory
) -> None:
    client, manual = await _client(env, http_client, Role.ADMIN)
    subject_id, teacher_id = new_id(), new_id()

    response = await client.post(
        f"/v1/admin/subjects/{subject_id}/emis-pull",
        json={
            "mode": "soft",
            "teacher_id": str(teacher_id),
            "terms": [{"academic_year": "2026-2027", "half": 1}],
        },
    )
    whole = await client.post(f"/v1/admin/subjects/{subject_id}/emis-pull", json={})

    assert response.status_code == 202 and whole.status_code == 202
    assert manual.calls == [
        {
            "subject_id": subject_id,
            "mode": "soft",
            "teacher_id": teacher_id,
            "group_id": None,
            "terms": [THIS_TERM],
        },
        {
            "subject_id": subject_id,
            "mode": "full",
            "teacher_id": None,
            "group_id": None,
            "terms": None,
        },
    ]


async def test_emis_pull_and_people_need_the_admin_role(
    env: Env, http_client: HttpClientFactory
) -> None:
    client, manual = await _client(env, http_client, Role.TEACHER)
    subject_id = new_id()

    pull = await client.post(f"/v1/admin/subjects/{subject_id}/emis-pull", json={})
    people = await client.get(f"/v1/admin/subjects/{subject_id}/people")

    assert pull.status_code == 403 and people.status_code == 403
    assert manual.calls == []


async def test_subject_people_lists_teachers_and_groups_of_the_term(
    env: Env, http_client: HttpClientFactory
) -> None:
    client, _ = await _client(env, http_client, Role.ADMIN)
    term = await env.term()
    math, physics = await env.subject(), await env.subject("Физика")
    a, b = await env.group("2TN2"), await env.group("1TN1")
    teacher = env.teacher()
    await env.entry(
        term, weekday=1, period=1, subject=math, audience=[f"{a.id}:1"], teacher=teacher
    )
    await env.entry(term, weekday=2, period=1, subject=math, audience=[str(b.id)])
    await env.entry(term, weekday=3, period=1, subject=physics, audience=[str(a.id)])

    found = await client.get(f"/v1/admin/subjects/{math.id}/people")
    missing = await client.get(f"/v1/admin/subjects/{new_id()}/people")

    assert found.json() == {
        "teachers": [{"id": str(teacher.id), "name": "Kalandarova Gulnora"}],
        "groups": [
            {"id": str(b.id), "name": "1TN1"},
            {"id": str(a.id), "name": "2TN2"},
        ],
    }
    assert missing.status_code == 404

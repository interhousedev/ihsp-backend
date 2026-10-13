"""UF-STF-06: the staff subject group routes over fake academic queries."""

from types import SimpleNamespace
from typing import Any, cast

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.staff_subjects import ROUTERS
from app.modules.academic.wiring_teaching import build_teaching
from app.shared.actor import Actor, Role
from app.shared.contracts.academic import (
    ClassworkQueries,
    MarkRef,
    MarksQueries,
    ScheduleQueries,
)
from app.shared.contracts.identity import IdentityDirectory, UserRef
from app.shared.ids import new_id
from app.shared.wiring import ModuleDeps
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
from httpx import AsyncClient

BASE = f"/v1/staff/subjects/{PHYSICS}/groups/{GROUP}"


@pytest.fixture
def schedule() -> Schedule:
    """The schedule fake."""
    return Schedule()


@pytest.fixture
def identity() -> FakeIdentity:
    """The identity fake."""
    return FakeIdentity()


@pytest.fixture
def marks() -> Marks:
    """The marks fake."""
    return Marks()


@pytest.fixture
def current() -> dict[str, Actor]:
    """The actor of the next request: a teacher by default."""
    return {"actor": Actor(user_id=new_id(), roles=frozenset({Role.TEACHER}))}


@pytest.fixture
def students(schedule: Schedule, identity: FakeIdentity) -> dict[int, UserRef]:
    """One student in each subgroup."""
    return {
        1: student_of(schedule, identity, "Alieva", 1),
        2: student_of(schedule, identity, "Bakirov", 2),
    }


@pytest.fixture
async def api(
    http_client: Any,
    schedule: Schedule,
    identity: FakeIdentity,
    marks: Marks,
    current: dict[str, Actor],
) -> AsyncClient:
    """A client of the routes; requests run as `current["actor"]`."""
    teaching = build_teaching(
        cast(ModuleDeps, SimpleNamespace(clock=FixedClock())),
        schedule=cast(ScheduleQueries, schedule),
        identity=cast(IdentityDirectory, identity),
        marks=cast(MarksQueries, marks),
        classwork=cast(ClassworkQueries, Classwork()),
    )
    client: AsyncClient = await http_client(
        ROUTERS,
        {get_actor: lambda: current["actor"]},
        academic=SimpleNamespace(teaching=teaching),
    )
    return client


async def test_subgroup_roster(
    api: AsyncClient,
    schedule: Schedule,
    current: dict[str, Actor],
    students: dict[int, UserRef],
) -> None:
    """UF-STF-06: the teacher of subgroup 1 gets its students and lessons."""
    teacher = current["actor"].user_id
    schedule.teacher_lessons[teacher] = [lesson(TODAY, f"{GROUP}:1")]

    response = await api.get(f"{BASE}/subgroups/1")

    assert response.status_code == 200
    body = response.json()
    assert body["subgroups"] == [1]
    assert [s["last_name"] for s in body["students"]] == ["Alieva"]
    assert len(body["lessons"]) == 1


async def test_other_subgroup_is_forbidden(
    api: AsyncClient,
    schedule: Schedule,
    current: dict[str, Actor],
    students: dict[int, UserRef],
) -> None:
    """UF-STF-06: the other subgroup answers 403 problem+json."""
    schedule.teacher_lessons[current["actor"].user_id] = [lesson(TODAY, f"{GROUP}:1")]

    group = await api.get(f"{BASE}/subgroups/2")
    student = await api.get(f"{BASE}/subgroups/2/students/{students[2].id}")

    assert group.status_code == 403
    assert group.headers["content-type"].startswith("application/problem+json")
    assert "academic/not-teaching-group" in group.json()["type"]
    assert student.status_code == 403


async def test_student_record_and_hidden_student(
    api: AsyncClient,
    schedule: Schedule,
    marks: Marks,
    current: dict[str, Actor],
    students: dict[int, UserRef],
) -> None:
    """UF-STF-06: the record of a taught student; another subgroup's is 404."""
    schedule.teacher_lessons[current["actor"].user_id] = [lesson(TODAY, f"{GROUP}:1")]
    marks.rows = [
        MarkRef(PHYSICS, "Physics", 1, "lesson", value, TODAY, None)
        for value in (5, 4, 4)
    ]

    record = await api.get(f"{BASE}/students/{students[1].id}")
    hidden = await api.get(f"{BASE}/students/{students[2].id}")

    assert record.status_code == 200
    assert record.json()["average"] == 4.33
    assert hidden.status_code == 404


async def test_admin_sees_any_student(
    api: AsyncClient, current: dict[str, Actor], students: dict[int, UserRef]
) -> None:
    """UF-STF-06: Administration opens any student's record."""
    current["actor"] = Actor(user_id=new_id(), roles=frozenset({Role.ADMIN}))

    response = await api.get(f"{BASE}/students/{students[2].id}")

    assert response.status_code == 200
    assert response.json()["student"]["last_name"] == "Bakirov"


async def test_student_role_is_forbidden(
    api: AsyncClient, current: dict[str, Actor]
) -> None:
    """UF-STF-06: students cannot use the staff routes."""
    current["actor"] = Actor(user_id=new_id(), roles=frozenset({Role.STUDENT}))

    response = await api.get(BASE)

    assert response.status_code == 403

"""GET /v1/me/teachers and the teacher contacts routes."""

import datetime as dt
from types import SimpleNamespace

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.me_teachers import ROUTERS
from app.modules.academic.domain import audience as audience_keys
from app.shared.actor import Role
from tests.academic.schedule.env import Env
from tests.conftest import HttpClientFactory
from tests.factories import make_actor

import pytest_asyncio
from httpx import AsyncClient

DAY = dt.date(2026, 10, 6)  # a Tuesday; the frozen clock is 09:00 UTC (14:00 local)


@pytest_asyncio.fixture
async def holder_client(
    env: Env, http_client: HttpClientFactory
) -> tuple[AsyncClient, dict[str, object]]:
    """The teacher routes over the env services; the caller is switchable."""
    holder: dict[str, object] = {"actor": make_actor(Role.ADMIN)}
    client = await http_client(
        ROUTERS,
        {get_actor: lambda: holder["actor"]},
        academic=SimpleNamespace(schedule=env.services),
        identity=SimpleNamespace(directory=env.identity, commands=env.commands),
    )
    return client, holder


async def test_a_student_sees_teachers_with_status_week_and_contacts(
    env: Env, holder_client: tuple[AsyncClient, dict[str, object]]
) -> None:
    client, holder = holder_client
    term = await env.term()
    math = await env.subject("Математика", short="Мат")
    physics = await env.subject("Физика", short="Физ")
    group = await env.group("2TN2")
    other = await env.group("1TN1", semester=1)
    room = await env.room("305")
    far = await env.room("207")
    student = await env.student(group)
    now_teacher = env.teacher("Gulnora", "Alieva")
    next_teacher = env.teacher("Bobur", "Zokirov")
    stranger = env.teacher("Nobody", "Else")
    whole = [audience_keys.key(group.id, None)]
    await env.lesson(
        term,
        day=DAY,
        period=5,
        subject=math,
        audience=whole,
        teacher=now_teacher,
        room=room,
    )
    await env.lesson(
        term,
        day=DAY,
        period=8,
        subject=physics,
        audience=whole,
        teacher=next_teacher,
        room=far,
    )
    await env.lesson(
        term,
        day=DAY,
        period=5,
        subject=physics,
        audience=[audience_keys.key(other.id, None)],
        teacher=stranger,
        room=far,
    )
    await env.commands.update_preferences(
        now_teacher.id,
        {"contacts": {"telegram": "@gulnora_a", "phone": "+998 90 123-45-67"}},
    )
    holder["actor"] = make_actor(Role.STUDENT, user_id=student.id)

    response = await client.get("/v1/me/teachers")

    assert response.status_code == 200
    body = response.json()
    assert [t["last_name"] for t in body] == ["Alieva", "Zokirov"]
    first, second = body
    assert first["teaching_now"] is True and first["current"]["room"] == "305"
    assert first["subjects"] == ["Математика"]
    assert first["contacts"]["telegram"] == "gulnora_a"
    assert second["teaching_now"] is False
    assert second["current"] is None and second["next"]["room"] == "207"
    assert second["contacts"]["telegram"] is None
    assert [w["weekday"] for w in first["week"]] == [2]
    assert first["week"][0]["group"] == "2TN2"


async def test_a_teacher_edits_own_contacts_and_bad_values_are_rejected(
    env: Env, holder_client: tuple[AsyncClient, dict[str, object]]
) -> None:
    client, holder = holder_client
    teacher = env.teacher()
    holder["actor"] = make_actor(Role.TEACHER, user_id=teacher.id)

    ok = await client.put(
        "/v1/staff/me/contacts",
        json={"email": "t@example.com", "office": "Каб. 12", "phone": ""},
    )
    bad_email = await client.put("/v1/staff/me/contacts", json={"email": "nope"})
    bad_phone = await client.put("/v1/staff/me/contacts", json={"phone": "abc"})
    read = await client.get("/v1/staff/me/contacts")

    assert ok.status_code == 200 and ok.json()["phone"] is None
    assert bad_email.status_code == 422 and bad_phone.status_code == 422
    assert (
        read.json()["email"] == "t@example.com" and read.json()["office"] == "Каб. 12"
    )


async def test_an_admin_edits_a_teacher_but_not_a_student(
    env: Env, holder_client: tuple[AsyncClient, dict[str, object]]
) -> None:
    client, holder = holder_client
    teacher = env.teacher()
    group = await env.group("2TN2")
    student = await env.student(group)
    holder["actor"] = make_actor(Role.ADMIN)

    ok = await client.put(
        f"/v1/admin/teacher-contacts/{teacher.id}", json={"office_hours": "Пн 15:00"}
    )
    missing = await client.put(
        f"/v1/admin/teacher-contacts/{student.id}", json={"office": "1"}
    )

    assert ok.status_code == 200 and ok.json()["office_hours"] == "Пн 15:00"
    assert missing.status_code == 404
    holder["actor"] = make_actor(Role.STUDENT)
    denied = await client.get(f"/v1/admin/teacher-contacts/{teacher.id}")
    assert denied.status_code == 403

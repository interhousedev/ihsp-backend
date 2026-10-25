"""GET /v1/me/teachers and the teacher contacts routes."""

import datetime as dt
from dataclasses import dataclass
from types import SimpleNamespace

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.me_teachers import ROUTERS
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.subject import Subject
from app.shared.actor import Role
from app.shared.contracts.identity import UserRef
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


# - - - one teacher and the teacher's timetable (fakes and PostgreSQL) - - -


@dataclass(slots=True)
class Taught:
    """A student of 2TN2, a teacher of 2TN2 (Tue) and 1TN1 (Wed, Sat), a stranger."""

    student: UserRef
    teacher: UserRef
    stranger: UserRef
    math: Subject


async def _taught(env: Env) -> Taught:
    term = await env.term()
    math = await env.subject("Математика", short="Мат")
    group = await env.group("2TN2")
    other = await env.group("1TN1", semester=1)
    taught = Taught(
        student=await env.student(group),
        teacher=env.teacher("Gulnora", "Alieva"),
        stranger=env.teacher("Nobody", "Else"),
        math=math,
    )
    room = await env.room("305")
    whole, theirs = audience_keys.key(group.id, None), audience_keys.key(other.id, None)
    for day, keys in ((DAY, whole), (DAY + dt.timedelta(days=1), theirs)):
        await env.lesson(
            term,
            day=day,
            period=2,
            subject=math,
            audience=[keys],
            teacher=taught.teacher,
            room=room,
        )
    await env.lesson(
        term,
        day=DAY + dt.timedelta(days=4),  # Saturday
        period=2,
        subject=math,
        audience=[theirs],
        teacher=taught.teacher,
    )
    await env.lesson(
        term,
        day=DAY,
        period=3,
        subject=math,
        audience=[theirs],
        teacher=taught.stranger,
    )
    return taught


async def test_a_student_opens_one_teacher_with_photo_subject_refs_and_upcoming(
    env: Env, holder_client: tuple[AsyncClient, dict[str, object]]
) -> None:
    client, holder = holder_client
    taught = await _taught(env)
    env.identity.photos[taught.teacher.id] = "https://photos.test/g.jpg"
    holder["actor"] = make_actor(Role.STUDENT, user_id=taught.student.id)

    response = await client.get(f"/v1/me/teachers/{taught.teacher.id}")
    listed = (await client.get("/v1/me/teachers")).json()

    assert response.status_code == 200
    body = response.json()
    assert body["last_name"] == "Alieva"
    assert body["photo_url"] == "https://photos.test/g.jpg"
    assert body["subjects"] == ["Математика"]
    assert body["subject_refs"] == [{"id": str(taught.math.id), "name": "Математика"}]
    assert [u["date"] for u in body["upcoming"]] == [DAY.isoformat()]
    assert body["upcoming"][0]["subject_id"] == str(taught.math.id)
    assert listed == [body]


async def test_an_unrelated_teacher_is_a_404_for_the_card_and_the_timetable(
    env: Env, holder_client: tuple[AsyncClient, dict[str, object]]
) -> None:
    client, holder = holder_client
    taught = await _taught(env)
    holder["actor"] = make_actor(Role.STUDENT, user_id=taught.student.id)

    card = await client.get(f"/v1/me/teachers/{taught.stranger.id}")
    table = await client.get(f"/v1/me/teachers/{taught.stranger.id}/timetable")

    assert card.status_code == 404 and table.status_code == 404
    holder["actor"] = make_actor(Role.TEACHER)
    denied = await client.get(f"/v1/me/teachers/{taught.teacher.id}/timetable")
    assert denied.status_code == 403


async def test_the_timetable_of_a_teacher_covers_all_groups_without_saturday(
    env: Env, holder_client: tuple[AsyncClient, dict[str, object]]
) -> None:
    client, holder = holder_client
    taught = await _taught(env)
    holder["actor"] = make_actor(Role.STUDENT, user_id=taught.student.id)
    url = f"/v1/me/teachers/{taught.teacher.id}/timetable"

    week = await client.get(url, params={"from": "2026-10-05", "to": "2026-10-11"})
    narrow = await client.get(url, params={"from": "2026-10-07", "to": "2026-10-07"})
    reversed_ = await client.get(url, params={"from": "2026-10-09", "to": "2026-10-07"})

    assert week.status_code == 200
    slots = week.json()
    assert [(s["date"], s["group"], s["mine"]) for s in slots] == [
        ("2026-10-06", "2TN2", True),
        ("2026-10-07", "1TN1", False),
    ]
    assert slots[0]["room"] == "305" and slots[0]["status"] == "scheduled"
    assert set(slots[0]) == {
        "id",
        "date",
        "starts_at",
        "ends_at",
        "subject_id",
        "subject_name",
        "room",
        "group",
        "mine",
        "status",
        "lesson_id",
    }
    assert [s["date"] for s in narrow.json()] == ["2026-10-07"]
    assert reversed_.status_code == 422


async def test_lessons_past_the_generated_ones_are_projected_for_the_teacher(
    env: Env, holder_client: tuple[AsyncClient, dict[str, object]]
) -> None:
    client, holder = holder_client
    term = await env.term()
    math = await env.subject("Математика", short="Мат")
    group = await env.group("2TN2")
    other = await env.group("1TN1", semester=1)
    student = await env.student(group)
    teacher = env.teacher()
    for weekday, target in ((2, group), (3, other)):
        await env.entry(
            term,
            weekday=weekday,
            period=1,
            subject=math,
            audience=[audience_keys.key(target.id, None)],
            teacher=teacher,
        )
    holder["actor"] = make_actor(Role.STUDENT, user_id=student.id)

    response = await client.get(
        f"/v1/me/teachers/{teacher.id}/timetable",
        params={"from": "2026-10-06", "to": "2026-10-14"},
    )

    assert response.status_code == 200
    assert [(s["date"], s["group"], s["mine"]) for s in response.json()] == [
        ("2026-10-06", "2TN2", True),
        ("2026-10-07", "1TN1", False),
        ("2026-10-13", "2TN2", True),
        ("2026-10-14", "1TN1", False),
    ]

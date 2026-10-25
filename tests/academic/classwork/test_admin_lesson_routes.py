"""Administration works on any lesson page route (web lesson page of the admin app)."""

import datetime as dt

from tests.academic.classwork.conftest import Env
from tests.academic.classwork.test_http import client_as
from tests.academic.classwork.world import DAY, add_lesson
from tests.conftest import HttpClientFactory


async def test_admin_opens_a_lesson_of_another_teacher(
    env: Env, http_client: HttpClientFactory
) -> None:
    """STF-4, ADM-10: GET /v1/staff/lessons/{id} accepts Administration."""
    lesson_id = await add_lesson(env.maker, env.world)
    env.links.add(lesson_id)
    admin = await client_as(http_client, env, env.admin)

    page = await admin.get(f"/v1/staff/lessons/{lesson_id}")

    assert page.status_code == 200
    body = page.json()
    assert body["lesson"]["id"] == str(lesson_id)
    assert body["attendance"]["editable"] is True
    assert len(body["attendance"]["roster"]) == 3


async def test_admin_sets_topic_and_homework_of_another_teachers_lesson(
    env: Env, http_client: HttpClientFactory
) -> None:
    """STF-7, ACA-21: topic and homework routes accept Administration."""
    lesson_id = await add_lesson(env.maker, env.world)
    await add_lesson(env.maker, env.world, day=DAY + dt.timedelta(days=7))
    admin = await client_as(http_client, env, env.admin)

    topic = await admin.put(
        f"/v1/staff/lessons/{lesson_id}/topic", json={"topic": "Waves"}
    )
    saved = await admin.put(
        f"/v1/staff/lessons/{lesson_id}/homework", json={"text": "Read page 5"}
    )
    removed = await admin.delete(f"/v1/staff/lessons/{lesson_id}/homework")

    assert topic.status_code == saved.status_code == removed.status_code == 200
    assert topic.json()["lesson"]["topic"] == "Waves"
    assert saved.json()["homework"]["text"] == "Read page 5"
    assert removed.json()["homework"] is None


async def test_admin_and_teacher_submit_attendance_for_an_old_lesson(
    env: Env, http_client: HttpClientFactory
) -> None:
    """ACA-11: no window; the teacher and Administration both edit old lessons."""
    w = env.world
    old = await add_lesson(env.maker, w, day=DAY - dt.timedelta(days=8))
    admin = await client_as(http_client, env, env.admin)
    teacher = await client_as(http_client, env, env.teacher)
    body = {"absent": [str(w.bobur.id)], "base_version": 0}

    by_teacher = await teacher.put(f"/v1/staff/lessons/{old}/attendance", json=body)
    by_admin = await admin.put(
        f"/v1/staff/lessons/{old}/attendance",
        json={"absent": [], "base_version": 1},
    )
    reopened = await admin.get(f"/v1/staff/lessons/{old}")

    assert by_teacher.status_code == 200
    assert by_admin.status_code == 200
    assert [row["absent"] for row in by_admin.json()["roster"]] == [False, False, False]
    assert reopened.json()["attendance"]["editable"] is True


async def test_admin_excuses_an_absence(
    env: Env, http_client: HttpClientFactory
) -> None:
    """ACA-20: the excuse route accepts Administration without being the curator."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)
    await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.aziz.id],
        base_version=0,
        source="staff",
    )
    admin = await client_as(http_client, env, env.admin)

    response = await admin.put(
        f"/v1/staff/lessons/{lesson_id}/attendance/excuse",
        json={"student_id": str(w.aziz.id), "excused": True, "comment": "Medical note"},
    )

    assert response.status_code == 200
    assert response.json()["roster"][0]["excused"] is True

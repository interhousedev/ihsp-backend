"""HTTP happy paths and error shapes of every B4 route (§ API contract)."""

import datetime as dt
from types import SimpleNamespace
from uuid import UUID

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_attendance import ROUTERS as ADMIN_ROUTERS
from app.interfaces.http.v1.me_classwork import ROUTERS as ME_ROUTERS
from app.interfaces.http.v1.staff_classwork import ROUTERS as STAFF_ROUTERS
from app.shared.actor import Actor
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import (
    DAY,
    add_lesson,
    add_mark,
    seed_attendance,
)
from tests.conftest import HttpClientFactory

from httpx import AsyncClient

ALL_ROUTERS = [*ME_ROUTERS, *STAFF_ROUTERS, *ADMIN_ROUTERS]


async def client_as(
    http_client: HttpClientFactory, env: Env, actor: Actor
) -> AsyncClient:
    """A client whose requests are authenticated as the actor."""
    return await http_client(
        ALL_ROUTERS,
        overrides={get_actor: lambda: actor},
        academic=SimpleNamespace(classwork=env.services),
    )


# - - - Student routes - - -


async def test_get_today(env: Env, http_client: HttpClientFactory) -> None:
    """GET /v1/me/today."""
    await add_lesson(env.maker, env.world, period=7)
    client = await client_as(http_client, env, env.student("aziz"))

    response = await client.get("/v1/me/today")

    assert response.status_code == 200
    body = response.json()
    assert body["now_or_next"]["subject"]["name"] == "Physics"
    assert body["lessons"][0]["state"] == "now"
    assert body["semester"]["semester"] == 2
    assert set(body) == {
        "now_or_next",
        "lessons",
        "next_study_day",
        "due",
        "new_marks",
        "semester",
        "synced_at",
    }


async def test_get_lesson_and_not_found_for_other_audiences(
    env: Env, http_client: HttpClientFactory
) -> None:
    """GET /v1/me/lessons/{id}."""
    lesson_id = await add_lesson(env.maker, env.world)
    await add_mark(
        env.maker, env.world.aziz.id, env.world.physics_id, lesson_id=lesson_id
    )
    client = await client_as(http_client, env, env.student("aziz"))
    outsider = await client_as(http_client, env, env.student("outsider"))

    response = await client.get(f"/v1/me/lessons/{lesson_id}")
    hidden = await outsider.get(f"/v1/me/lessons/{lesson_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["lesson"]["id"] == str(lesson_id)
    assert body["my_mark"][0]["value"] == 5
    assert body["my_attendance"] == "not_taken"
    assert body["can_attach"] is True
    assert hidden.status_code == 404
    assert hidden.json()["type"] == "academic/lesson-not-found"


async def test_homework_list_tick_and_note(
    env: Env, http_client: HttpClientFactory
) -> None:
    """GET /v1/me/homework, PUT .../done, PUT .../note."""
    w = env.world
    await add_lesson(env.maker, w, day=DAY + dt.timedelta(days=1))
    lesson_id = await add_lesson(
        env.maker,
        w,
        homework_text="Read page 5",
        homework_due_date=DAY + dt.timedelta(days=1),
        homework_due_auto=False,
    )
    client = await client_as(http_client, env, env.student("aziz"))

    upcoming = await client.get("/v1/me/homework")
    done = await client.put(f"/v1/me/homework/{lesson_id}/done", json={"done": True})
    note = await client.put(
        f"/v1/me/homework/{lesson_id}/note", json={"note": "hard part"}
    )
    in_done = await client.get("/v1/me/homework", params={"status": "done"})
    too_long = await client.put(
        f"/v1/me/homework/{lesson_id}/note", json={"note": "x" * 1001}
    )

    assert [item["text"] for item in upcoming.json()] == ["Read page 5"]
    assert done.status_code == 200
    assert done.json()["done_at"] is not None
    assert note.json()["note"] == "hard part"
    assert [item["lesson_id"] for item in in_done.json()] == [str(lesson_id)]
    assert too_long.status_code == 422
    assert too_long.json()["type"] == "homework/note-too-long"


async def test_get_attendance_uses_from_and_to(
    env: Env, http_client: HttpClientFactory
) -> None:
    """GET /v1/me/attendance?from&to."""
    await seed_attendance(env.maker, env.world)
    client = await client_as(http_client, env, env.student("aziz"))

    response = await client.get(
        "/v1/me/attendance", params={"from": "2026-09-26", "to": "2026-10-06"}
    )

    body = response.json()
    assert response.status_code == 200
    assert body["from"] == "2026-09-26"
    assert body["to"] == "2026-10-06"
    assert body["summary"][0]["absences"] == 2
    assert body["summary"][0]["rate"] == 0.6667
    assert [d["date"] for d in body["days"]] == ["2026-10-01", "2026-10-04"]
    assert len(body["missed"]) == 2
    assert body["not_taken"] == 2


async def test_student_routes_refuse_other_roles(
    env: Env, http_client: HttpClientFactory
) -> None:
    """§ API contract: student role required."""
    client = await client_as(http_client, env, env.teacher)

    response = await client.get("/v1/me/today")

    assert response.status_code == 403
    assert response.json()["type"] == "common/forbidden"


# - - - Staff routes - - -


async def test_staff_today_and_lesson(env: Env, http_client: HttpClientFactory) -> None:
    """GET /v1/staff/today, GET /v1/staff/lessons/{id}."""
    lesson_id = await add_lesson(env.maker, env.world)
    env.links.add(lesson_id)
    client = await client_as(http_client, env, env.teacher)

    today = await client.get("/v1/staff/today")
    page = await client.get(f"/v1/staff/lessons/{lesson_id}")

    assert today.status_code == 200
    assert today.json()["lessons"][0]["attendance_missing"] is True
    assert page.status_code == 200
    body = page.json()
    assert body["attendance"]["editable"] is True
    assert len(body["attendance"]["roster"]) == 3
    assert body["materials"][0]["file"] is None
    assert body["homework"] is None


async def test_staff_lesson_is_forbidden_for_another_teacher(
    env: Env, http_client: HttpClientFactory
) -> None:
    """GET /v1/staff/lessons/{id}: the teacher of the lesson, or admin."""
    lesson_id = await add_lesson(env.maker, env.world)
    client = await client_as(http_client, env, env.other_teacher)

    response = await client.get(f"/v1/staff/lessons/{lesson_id}")

    assert response.status_code == 403
    assert response.json()["type"] == "academic/not-lesson-teacher"


async def test_homework_put_delete_and_topic(
    env: Env, http_client: HttpClientFactory
) -> None:
    """PUT/DELETE /v1/staff/lessons/{id}/homework, PUT .../topic."""
    lesson_id = await add_lesson(env.maker, env.world)
    await add_lesson(env.maker, env.world, day=DAY + dt.timedelta(days=7))
    client = await client_as(http_client, env, env.teacher)

    saved = await client.put(
        f"/v1/staff/lessons/{lesson_id}/homework", json={"text": "Read page 5"}
    )
    topic = await client.put(
        f"/v1/staff/lessons/{lesson_id}/topic", json={"topic": "Waves"}
    )
    removed = await client.delete(f"/v1/staff/lessons/{lesson_id}/homework")

    assert saved.status_code == 200
    assert saved.json()["homework"] == {
        "text": "Read page 5",
        "due_date": "2026-10-13",
        "due_auto": True,
    }
    assert topic.json()["lesson"]["topic"] == "Waves"
    assert removed.status_code == 200
    assert removed.json()["homework"] is None
    assert removed.json()["lesson"]["topic"] == "Waves"


async def test_attendance_put_conflict_and_old_lesson(
    env: Env, http_client: HttpClientFactory
) -> None:
    """PUT /v1/staff/lessons/{id}/attendance: 409 with the sheet, old lessons ok."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)
    old = await add_lesson(env.maker, w, day=DAY - dt.timedelta(days=8))
    client = await client_as(http_client, env, env.teacher)
    body = {"absent": [str(w.bobur.id)], "base_version": 0}

    saved = await client.put(f"/v1/staff/lessons/{lesson_id}/attendance", json=body)
    stale = await client.put(f"/v1/staff/lessons/{lesson_id}/attendance", json=body)
    late = await client.put(
        f"/v1/staff/lessons/{old}/attendance", json={"absent": [], "base_version": 0}
    )

    assert saved.status_code == 200
    assert saved.json()["version"] == 1
    assert [r["absent"] for r in saved.json()["roster"]] == [False, True, False]
    assert stale.status_code == 409
    problem = stale.json()
    assert problem["type"] == "common/conflict"
    assert problem["params"]["current"]["version"] == 1
    assert late.status_code == 200


async def test_attendance_put_with_unassigned_students(
    env: Env, http_client: HttpClientFactory
) -> None:
    """The contract addition: present_unassigned."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w, audience=[f"{w.group_id}:1"])
    client = await client_as(http_client, env, env.teacher)

    response = await client.put(
        f"/v1/staff/lessons/{lesson_id}/attendance",
        json={
            "absent": [],
            "present_unassigned": [str(w.camila.id)],
            "base_version": 0,
        },
    )

    roster = {r["last_name"]: r for r in response.json()["roster"]}
    assert response.status_code == 200
    assert roster["Rakhimova"]["subgroup_unset"] is True
    assert roster["Rakhimova"]["counted"] is True


async def test_excuse_route(env: Env, http_client: HttpClientFactory) -> None:
    """PUT /v1/staff/lessons/{id}/attendance/excuse."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)
    await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.aziz.id],
        base_version=0,
        source="staff",
    )
    curator = await client_as(http_client, env, env.curator)
    outsider = await client_as(http_client, env, env.other_teacher)
    body = {"student_id": str(w.aziz.id), "excused": True, "comment": "Medical note"}

    ok = await curator.put(
        f"/v1/staff/lessons/{lesson_id}/attendance/excuse", json=body
    )
    refused = await outsider.put(
        f"/v1/staff/lessons/{lesson_id}/attendance/excuse", json=body
    )

    assert ok.status_code == 200
    assert ok.json()["roster"][0]["excused"] is True
    assert ok.json()["roster"][0]["excuse_comment"] == "Medical note"
    assert refused.status_code == 403
    assert refused.json()["type"] == "academic/not-curator"


async def test_journal_routes(env: Env, http_client: HttpClientFactory) -> None:
    """GET /v1/staff/journal, /options, /journal.csv and POST /journal/toggle."""
    w = env.world
    ids = await seed_attendance(env.maker, w)
    client = await client_as(http_client, env, env.teacher)
    query = {"subject_id": str(w.physics_id), "audience_key": str(w.group_id)}

    options = await client.get("/v1/staff/journal/options")
    journal = await client.get("/v1/staff/journal", params=query)
    toggled = await client.post(
        "/v1/staff/journal/toggle",
        json={
            "lesson_id": str(ids["today"]),
            "student_id": str(w.aziz.id),
            "absent": True,
            "base_version": 0,
        },
    )
    stale = await client.post(
        "/v1/staff/journal/toggle",
        json={
            "lesson_id": str(ids["today"]),
            "student_id": str(w.bobur.id),
            "absent": True,
            "base_version": 0,
        },
    )
    csv = await client.get("/v1/staff/journal.csv", params=query)

    assert options.json()[0]["label"] == "2TN2"
    assert options.json()[0]["audience_key"] == str(w.group_id)
    assert journal.status_code == 200
    assert len(journal.json()["lessons"]) == 4
    assert len(journal.json()["students"]) == 3
    assert toggled.json() == {"attendance_version": 1}
    assert stale.status_code == 409
    assert stale.json()["type"] == "common/conflict"
    assert csv.status_code == 200
    assert csv.headers["content-type"].startswith("text/csv")
    assert "attachment" in csv.headers["content-disposition"]
    assert csv.content.startswith(b"\xef\xbb\xbf")


async def test_curator_group_routes(env: Env, http_client: HttpClientFactory) -> None:
    """GET /v1/staff/groups/{id}/attendance, .csv and /students."""
    w = env.world
    await seed_attendance(env.maker, w)
    client = await client_as(http_client, env, env.curator)
    stranger = await client_as(http_client, env, env.other_teacher)
    base = f"/v1/staff/groups/{w.group_id}"
    window = {"from": "2026-09-26", "to": "2026-10-06"}

    report = await client.get(
        f"{base}/attendance", params={"view": "student", **window}
    )
    csv = await client.get(f"{base}/attendance.csv", params={"view": "day", **window})
    students = await client.get(f"{base}/students")
    refused = await stranger.get(f"{base}/students")

    assert report.status_code == 200
    body = report.json()
    assert body["view"] == "student"
    assert body["from"] == "2026-09-26"
    assert body["rows"][0] == {
        "key": str(w.aziz.id),
        "label": "Abdullaev Aziz",
        "absences": 2,
        "excused": 1,
        "lessons": 3,
        "rate": 0.6667,
        "not_taken": 2,
    }
    assert csv.status_code == 200
    assert csv.content.startswith(b"\xef\xbb\xbf")
    assert [s["last_name"] for s in students.json()] == [
        "Abdullaev",
        "Karimov",
        "Rakhimova",
    ]
    assert students.json()[0]["flags"] == ["absences"]
    assert refused.status_code == 403
    assert refused.json()["type"] == "academic/not-curator"


# - - - Admin routes - - -


async def test_admin_attendance_routes(
    env: Env, http_client: HttpClientFactory
) -> None:
    """GET /v1/admin/attendance, /missing and /attendance.csv."""
    ids = await seed_attendance(env.maker, env.world)
    admin = await client_as(http_client, env, env.admin)
    teacher = await client_as(http_client, env, env.teacher)
    window = {"from": "2026-09-26", "to": "2026-10-06"}

    report = await admin.get("/v1/admin/attendance", params={"view": "group", **window})
    missing = await admin.get("/v1/admin/attendance/missing", params=window)
    csv = await admin.get(
        "/v1/admin/attendance.csv", params={"view": "teacher", **window}
    )
    refused = await teacher.get("/v1/admin/attendance")

    assert report.status_code == 200
    assert report.json()["rows"][0]["label"] == "2TN2"
    assert report.json()["rows"][0]["absences"] == 3
    assert missing.status_code == 200
    assert [row["teacher"]["last_name"] for row in missing.json()] == [
        "Kalandarova",
        "Yusupov",
    ]
    assert missing.json()[0]["lessons"][0]["id"] == str(ids["today"])
    assert csv.status_code == 200
    assert csv.content.startswith(b"\xef\xbb\xbf")
    assert refused.status_code == 403


async def test_unknown_lesson_is_404_problem_json(
    env: Env, http_client: HttpClientFactory
) -> None:
    """§ 3.7: errors are problem+json with a stable type."""
    client = await client_as(http_client, env, env.teacher)

    response = await client.get(f"/v1/staff/lessons/{UUID(int=1)}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["message_key"] == "academic-lesson-not-found"

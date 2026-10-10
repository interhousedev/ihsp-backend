"""HTTP happy paths of the student marks pages and the sync monitor."""

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_sync import ROUTERS as ADMIN_ROUTERS
from app.interfaces.http.v1.me_marks import ROUTERS as MARKS_ROUTERS
from app.modules.academic.wiring_marks import MarksServices
from app.shared.actor import Role
from tests.academic.marks.conftest import Env
from tests.fakes.clock import FixedClock


async def _client(
    http_client: Any, services: MarksServices, actor: Any, routers: Any
) -> Any:
    return await http_client(
        routers,
        {get_actor: lambda: actor},
        academic=SimpleNamespace(marks=services),
    )


async def test_subject_cards(
    http_client: Any, services: MarksServices, env: Env, make_actor: Any
) -> None:
    """WEB-7: cards sorted by name with marks, teacher, absences and the next lesson."""
    actor = make_actor(Role.STUDENT, user_id=env.world.user_id)
    client = await _client(http_client, services, actor, MARKS_ROUTERS)
    env.identity.photos[env.world.teacher_id] = "https://photos.test/bobur.jpg"

    response = await client.get("/v1/me/subjects")

    assert response.status_code == 200
    physics, math = response.json()
    assert physics["subject"] == {
        "id": str(env.world.physics_id),
        "name": "Fizika",  # no English name: falls back to uz
        "short_name": "Fizika",
    }
    assert physics["semester_mark"] == 3.0
    assert math["subject"]["name"] == "Mathematics"
    assert math["subject"]["short_name"] == "Math"
    assert math["semester_mark"] == 4.5  # lesson 4.0 and midterm 5.0, no final yet
    assert math["emis_rating"] == 90
    assert math["absences"] == 1
    assert math["teachers"] == [
        {
            "id": str(env.world.teacher_id),
            "first_name": "Bobur",
            "last_name": "Aliev",
            "photo_url": "https://photos.test/bobur.jpg",
        }
    ]
    assert len(env.identity.photo_calls) == 1  # one batch for the whole page
    assert math["next_lesson"]["id"] == str(env.world.math_next)
    assert math["next_lesson"]["audience"] == [
        {"group_id": str(env.world.group_id), "group_name": "2TN2", "subgroup": None}
    ]


async def test_subject_detail(
    http_client: Any, services: MarksServices, env: Env, make_actor: Any
) -> None:
    """WEB-8: averages, lessons with marks and attendance, marks, visible materials."""
    w = env.world
    client = await _client(
        http_client,
        services,
        make_actor(Role.STUDENT, user_id=w.user_id),
        MARKS_ROUTERS,
    )

    env.identity.photos[w.teacher_id] = "https://photos.test/bobur.jpg"

    response = await client.get(f"/v1/me/subjects/{w.math_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["semester"] == 3
    assert [t["photo_url"] for t in body["teachers"]] == [
        "https://photos.test/bobur.jpg"
    ]
    assert body["lessons"][0]["teacher"]["photo_url"] is None  # lesson items: no photo
    assert len(env.identity.photo_calls) == 1
    assert body["averages"] == {"lesson": 4.0, "midterm": 5.0, "final": None}
    assert body["absence_rate"] == 1.0
    lessons = {item["id"]: item for item in body["lessons"]}
    assert list(lessons) == [
        str(w.math_lesson_1),
        str(w.math_lesson_2),
        str(w.math_next),
    ]
    first = lessons[str(w.math_lesson_1)]
    assert first["attendance"] == "absent"
    assert sorted(m["value"] for m in first["marks"]) == [4, 5, 5]
    assert lessons[str(w.math_lesson_2)]["attendance"] == "not_taken"
    assert len(body["marks"]) == 4
    assert [m["title"] for m in body["materials"]] == ["notes"]
    assert body["materials"][0]["author"]["last_name"] == "Aliev"


async def test_unknown_subject_is_404(
    http_client: Any, services: MarksServices, env: Env, make_actor: Any
) -> None:
    """A subject outside the student's curriculum is not found."""
    client = await _client(
        http_client,
        services,
        make_actor(Role.STUDENT, user_id=env.world.user_id),
        MARKS_ROUTERS,
    )

    response = await client.get(f"/v1/me/subjects/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["type"] == "academic/subject-not-found"


async def test_grades_table(
    http_client: Any, services: MarksServices, env: Env, make_actor: Any
) -> None:
    """WEB-12: GPA, one row per subject and the last sync time."""
    client = await _client(
        http_client,
        services,
        make_actor(Role.STUDENT, user_id=env.world.user_id),
        MARKS_ROUTERS,
    )

    body = (await client.get("/v1/me/grades?semester=3")).json()

    assert body["semester"] == 3
    assert body["gpa"] == 4.0  # marks 5, 4, 3, 5 and 3: 20 / 5
    rows = {r["subject"]["name"]: r for r in body["rows"]}
    assert rows["Mathematics"]["midterm_avg"] == 5.0
    assert rows["Mathematics"]["marks_count"] == 4
    assert body["synced_at"].startswith("2026-10-06T09:00:00")


async def test_marks_of_a_day(
    http_client: Any, services: MarksServices, env: Env, make_actor: Any
) -> None:
    """WEB-14: marks sit on the first lesson of their subject; others are unmatched."""
    w = env.world
    client = await _client(
        http_client,
        services,
        make_actor(Role.STUDENT, user_id=w.user_id),
        MARKS_ROUTERS,
    )

    day = (await client.get("/v1/me/grades/day?date=2026-10-06")).json()
    assert [item["lesson"]["id"] for item in day["lessons"]] == [
        str(w.math_lesson_1),
        str(w.math_lesson_2),
        str(w.physics_lesson),
    ]
    assert sorted(m["value"] for m in day["lessons"][0]["marks"]) == [4, 5, 5]
    assert day["lessons"][1]["marks"] == []
    assert [m["value"] for m in day["lessons"][2]["marks"]] == [3]
    assert day["unmatched"] == []

    other = (await client.get("/v1/me/grades/day?date=2026-10-07")).json()
    assert other["lessons"] == []
    assert [m["value"] for m in other["unmatched"]] == [3]


async def test_record_book(
    http_client: Any, services: MarksServices, env: Env, make_actor: Any
) -> None:
    """WEB-15: semesters with results, GPA and subject marks."""
    client = await _client(
        http_client,
        services,
        make_actor(Role.STUDENT, user_id=env.world.user_id),
        MARKS_ROUTERS,
    )

    body = (await client.get("/v1/me/record-book")).json()

    assert [s["semester"] for s in body["semesters"]] == [3]
    assert [s["subject"]["name"] for s in body["semesters"][0]["subjects"]] == [
        "Fizika",
        "Mathematics",
    ]


async def test_access_rules(
    http_client: Any, services: MarksServices, env: Env, make_actor: Any
) -> None:
    """Teachers get 403, a user without a student record 404, a bad semester 422."""
    teacher = await _client(
        http_client, services, make_actor(Role.TEACHER), MARKS_ROUTERS
    )
    assert (await teacher.get("/v1/me/grades")).status_code == 403

    stranger = await _client(
        http_client, services, make_actor(Role.STUDENT), MARKS_ROUTERS
    )
    response = await stranger.get("/v1/me/grades")
    assert response.status_code == 404
    assert response.json()["type"] == "academic/student-not-found"

    student = await _client(
        http_client,
        services,
        make_actor(Role.STUDENT, user_id=env.world.user_id),
        MARKS_ROUTERS,
    )
    assert (await student.get("/v1/me/grades?semester=5")).status_code == 422
    assert (await student.get("/v1/me/grades/day")).status_code == 422


async def test_admin_sync_monitor(
    http_client: Any, services: MarksServices, env: Env, kicker: Any, make_actor: Any
) -> None:
    """ADM-14: list runs, start a full or a single-student run, students are refused."""
    await env.sync_all().execute("11:30")
    admin = await _client(http_client, services, make_actor(Role.ADMIN), ADMIN_ROUTERS)

    runs = (await admin.get("/v1/admin/sync/runs")).json()
    assert runs["next_cursor"] is None
    assert runs["items"][0]["status"] == "done"
    assert runs["items"][0]["stats"]["students_total"] == 1

    assert (await admin.post("/v1/admin/sync/run", json={})).status_code == 202
    response = await admin.post(
        "/v1/admin/sync/run", json={"user_id": str(env.world.user_id)}
    )
    assert response.status_code == 202
    assert kicker.calls == [
        ("academic.sync_all", {"slot": "manual"}),
        (
            "academic.sync_student",
            {"user_id": str(env.world.user_id), "mode": "profile"},
        ),
    ]

    unknown = await admin.post("/v1/admin/sync/run", json={"user_id": str(uuid4())})
    assert unknown.status_code == 404

    student = await _client(
        http_client, services, make_actor(Role.STUDENT), ADMIN_ROUTERS
    )
    assert (await student.get("/v1/admin/sync/runs")).status_code == 403
    assert (await student.post("/v1/admin/sync/run", json={})).status_code == 403


def test_fixed_clock_is_shared(env: Env) -> None:
    """The use cases and the tests share one clock (guards the fixtures)."""
    assert isinstance(env.clock, FixedClock)

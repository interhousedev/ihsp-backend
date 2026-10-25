"""HTTP: the student calendar, the staff editor and the admin list."""

import datetime as dt
from types import SimpleNamespace
from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_assessments import ROUTERS as ADMIN_ROUTERS
from app.interfaces.http.v1.me_assessments import ROUTERS as ME_ROUTERS
from app.interfaces.http.v1.staff_assessments import ROUTERS as STAFF_ROUTERS
from app.modules.academic.application.assessments.inputs import AssessmentInput
from app.shared.actor import Actor
from tests.academic.assessments.conftest import Env, add_exam_lesson

D = dt.date.fromisoformat


async def _client(http_client: Any, env: Env, actor: Actor, routers: Any) -> Any:
    return await http_client(
        routers,
        {get_actor: lambda: actor},
        academic=SimpleNamespace(assessments=env.services),
    )


def _body(env: Env, **kwargs: object) -> dict[str, object]:
    body: dict[str, object] = {
        "subject_id": str(env.world.math_id),
        "audience": [{"group_id": str(env.world.group_id), "subgroup": None}],
        "kind": "midterm",
        "date": "2026-10-21",
    }
    body.update(kwargs)
    return body


async def test_the_student_gets_items_with_the_documented_shape(
    http_client: Any, env: Env
) -> None:
    """GET /v1/me/assessments?from=&to=&subject_id= gives {items: AssessmentItem[]}."""
    client = await _client(http_client, env, env.student(), ME_ROUTERS)

    response = await client.get(
        "/v1/me/assessments",
        params={
            "from": "2026-10-06",
            "to": "2026-10-20",
            "subject_id": str(env.world.math_id),
        },
    )

    assert response.status_code == 200
    (item,) = response.json()["items"]
    assert set(item) == {
        "id",
        "subject",
        "kind",
        "title",
        "date",
        "starts_at",
        "lesson_id",
        "room",
        "status",
        "source",
        "note",
        "days_left",
        "control",
        "period",
        "has_date",
    }
    assert item["subject"] == {
        "id": str(env.world.math_id),
        "name": "Mathematics",
        "short_name": "Math",
    }
    assert (item["date"], item["days_left"], item["has_date"]) == (
        "2026-10-19",
        13,
        False,
    )
    assert item["period"] == {"start": "2026-10-19", "end": "2026-10-24"}


async def test_a_teacher_cannot_read_the_student_calendar(
    http_client: Any, env: Env
) -> None:
    """403: the route is for students."""
    client = await _client(http_client, env, env.teacher(), ME_ROUTERS)

    assert (await client.get("/v1/me/assessments")).status_code == 403


async def test_the_head_student_suggests_a_date(http_client: Any, env: Env) -> None:
    """POST /v1/me/assessments -> 201 tentative; others get 403."""
    payload = {
        "subject_id": str(env.world.math_id),
        "kind": "final",
        "date": "2026-12-16",
        "note": "Hall A",
    }
    head = await _client(http_client, env, env.head(), ME_ROUTERS)
    other = await _client(http_client, env, env.student(), ME_ROUTERS)

    created = await head.post("/v1/me/assessments", json=payload)
    refused = await other.post("/v1/me/assessments", json=payload)
    again = await head.post("/v1/me/assessments", json=payload)

    assert created.status_code == 201
    assert (created.json()["status"], created.json()["source"]) == (
        "tentative",
        "head_student",
    )
    assert created.json()["control"] == "final"
    assert refused.status_code == 403
    assert refused.json()["type"] == "academic/not-head-student"
    assert again.status_code == 409


async def test_the_teacher_runs_the_staff_editor(http_client: Any, env: Env) -> None:
    """POST, GET, PATCH (confirm / edit / clear) and DELETE of /v1/staff/assessments."""
    client = await _client(http_client, env, env.teacher(), STAFF_ROUTERS)

    created = await client.post(
        "/v1/staff/assessments", json=_body(env, room="204", note="Ruler")
    )
    assert created.status_code == 201
    item = created.json()
    assert (item["status"], item["source"], item["room"]) == (
        "planned",
        "teacher",
        "204",
    )
    assert item["audience"][0]["group_name"] == "2TN2"

    patched = await client.patch(
        f"/v1/staff/assessments/{item['id']}",
        json={"room": None, "title": "Algebra", "status": "planned"},
    )
    assert patched.status_code == 200
    assert (patched.json()["room"], patched.json()["title"]) == (None, "Algebra")
    assert patched.json()["note"] == "Ruler"  # not sent: unchanged

    listed = await client.get(
        "/v1/staff/assessments", params={"from": "2026-10-01", "kind": "midterm"}
    )
    assert [i["id"] for i in listed.json()["items"]] == [item["id"]]

    deleted = await client.delete(f"/v1/staff/assessments/{item['id']}")
    assert deleted.status_code == 204
    assert (await client.get("/v1/staff/assessments")).json() == {"items": []}
    gone = await client.get("/v1/staff/assessments", params={"status": "cancelled"})
    assert [i["id"] for i in gone.json()["items"]] == [item["id"]]


async def test_staff_errors_use_the_documented_status_codes(
    http_client: Any, env: Env
) -> None:
    """403 for a stranger, 404 for an unknown id, 422 for a bad body."""
    stranger = await _client(http_client, env, env.stranger(), STAFF_ROUTERS)
    teacher = await _client(http_client, env, env.teacher(), STAFF_ROUTERS)

    forbidden = await stranger.post("/v1/staff/assessments", json=_body(env))
    missing = await teacher.patch(
        "/v1/staff/assessments/00000000-0000-0000-0000-000000000001", json={}
    )
    invalid = await teacher.post("/v1/staff/assessments", json=_body(env, audience=[]))
    wrong_kind = await teacher.post(
        "/v1/staff/assessments", json=_body(env, kind="oral")
    )
    mismatch = await teacher.post(
        "/v1/staff/assessments", json=_body(env, control="final")
    )

    assert forbidden.status_code == 403
    assert forbidden.json()["type"] == "academic/not-assessment-teacher"
    assert missing.status_code == 404
    assert invalid.status_code == 422
    assert wrong_kind.status_code == 422
    assert mismatch.status_code == 422
    assert mismatch.json()["type"] == "academic/invalid-assessment"


async def test_a_student_cannot_use_the_staff_routes(
    http_client: Any, env: Env
) -> None:
    """The role check runs before anything else."""
    client = await _client(http_client, env, env.student(), STAFF_ROUTERS)

    assert (await client.get("/v1/staff/assessments")).status_code == 403
    assert (
        await client.post("/v1/staff/assessments", json=_body(env))
    ).status_code == 403


async def test_a_teacher_confirms_an_emis_suggestion_over_http(
    http_client: Any, env: Env
) -> None:
    """The "confirm EMIS suggestion" flow of the staff portal."""
    await add_exam_lesson(env, D("2026-11-10"))
    await env.services.generate_suggestions.execute()
    client = await _client(http_client, env, env.teacher(), STAFF_ROUTERS)
    (suggestion,) = (
        await client.get("/v1/staff/assessments", params={"status": "tentative"})
    ).json()["items"]
    assert (suggestion["status"], suggestion["source"]) == ("tentative", "emis")

    confirmed = await client.patch(
        f"/v1/staff/assessments/{suggestion['id']}", json={"status": "planned"}
    )

    assert confirmed.json()["status"] == "planned"


async def test_staff_can_ask_for_the_weeks_without_a_date(
    http_client: Any, env: Env
) -> None:
    """?undated=true adds the control weeks nobody dated for a subject."""
    client = await _client(http_client, env, env.teacher(), STAFF_ROUTERS)

    items = (
        await client.get("/v1/staff/assessments", params={"undated": "true"})
    ).json()["items"]

    assert len(items) == 6
    assert all(i["has_date"] is False for i in items)
    assert items[0]["created_at"] is None
    assert items[0]["audience"][0]["group_name"] == "2TN2"


async def test_the_admin_list_filters_and_manages_every_group(
    http_client: Any, env: Env
) -> None:
    """GET/POST/PATCH/DELETE under /v1/admin/assessments; teachers get 403."""
    admin = await _client(http_client, env, env.admin(), ADMIN_ROUTERS)
    teacher = await _client(http_client, env, env.teacher(), ADMIN_ROUTERS)
    await env.services.create.execute(
        env.admin(),
        AssessmentInput(
            subject_id=env.world.physics_id,
            audience=[(env.world.group_id, None)],
            kind="final",
            date=D("2026-12-15"),
        ),
    )

    created = await admin.post("/v1/admin/assessments", json=_body(env))
    listed = await admin.get("/v1/admin/assessments")
    finals = await admin.get("/v1/admin/assessments", params={"kind": "final"})
    by_source = await admin.get("/v1/admin/assessments", params={"source": "admin"})
    patched = await admin.patch(
        f"/v1/admin/assessments/{created.json()['id']}", json={"status": "cancelled"}
    )
    forbidden = await teacher.get("/v1/admin/assessments")

    assert created.status_code == 201
    assert created.json()["source"] == "admin"
    assert len(listed.json()["items"]) == 2
    assert [i["kind"] for i in finals.json()["items"]] == ["final"]
    assert len(by_source.json()["items"]) == 2
    assert patched.json()["status"] == "cancelled"
    assert (
        await admin.delete(f"/v1/admin/assessments/{created.json()['id']}")
    ).status_code == 204
    assert forbidden.status_code == 403

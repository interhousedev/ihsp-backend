"""WO-1, WO-3, WO-6, WO-8: HTTP routes of the work-off tasks."""

from types import SimpleNamespace
from uuid import UUID, uuid4

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_work_offs import ROUTERS as ADMIN_ROUTERS
from app.interfaces.http.v1.me_classwork import ROUTERS as ME_ROUTERS
from app.interfaces.http.v1.staff_classwork import ROUTERS as STAFF_ROUTERS
from app.interfaces.http.v1.staff_work_offs import ROUTERS as WORK_OFF_ROUTERS
from app.shared.actor import Actor
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import DAY, add_lesson
from tests.conftest import HttpClientFactory

from httpx import AsyncClient

ROUTERS = [*ME_ROUTERS, *STAFF_ROUTERS, *WORK_OFF_ROUTERS, *ADMIN_ROUTERS]


async def client_as(
    http_client: HttpClientFactory, env: Env, actor: Actor
) -> AsyncClient:
    """A client whose requests are authenticated as the actor."""
    return await http_client(
        ROUTERS,
        overrides={get_actor: lambda: actor},
        academic=SimpleNamespace(classwork=env.services),
    )


async def submit(client: AsyncClient, lesson_id: UUID, **extra: object) -> dict:
    """PUT the attendance and return the sheet."""
    response = await client.put(
        f"/v1/staff/lessons/{lesson_id}/attendance",
        json={"base_version": 0, **extra},
    )
    assert response.status_code == 200, response.text
    sheet: dict = response.json()
    return sheet


# - - - Templates - - -


async def test_template_crud_is_private_to_the_owner(
    env: Env, http_client: HttpClientFactory
) -> None:
    """WO-1: create, list, update, delete; a foreign template is a 404."""
    mine = await client_as(http_client, env, env.teacher)
    other = await client_as(http_client, env, env.other_teacher)
    student = await client_as(http_client, env, env.student("aziz"))

    created = await mine.post(
        "/v1/staff/work-off-templates", json={"text": "Redo ex. 4", "is_default": True}
    )
    tpl = created.json()["id"]
    listed = await mine.get("/v1/staff/work-off-templates")
    updated = await mine.put(
        f"/v1/staff/work-off-templates/{tpl}", json={"text": "Essay"}
    )
    foreign_put = await other.put(
        f"/v1/staff/work-off-templates/{tpl}", json={"text": "x"}
    )
    foreign_delete = await other.delete(f"/v1/staff/work-off-templates/{tpl}")
    refused = await student.get("/v1/staff/work-off-templates")
    deleted = await mine.delete(f"/v1/staff/work-off-templates/{tpl}")

    assert created.status_code == 201
    assert set(created.json()) == {
        "id",
        "text",
        "is_default",
        "created_at",
        "updated_at",
    }
    assert [t["id"] for t in listed.json()] == [tpl]
    assert updated.json()["text"] == "Essay"
    assert updated.json()["is_default"] is False
    assert foreign_put.status_code == 404
    assert foreign_put.json()["type"] == "work-off/template-not-found"
    assert foreign_delete.status_code == 404
    assert refused.status_code == 403
    assert deleted.status_code == 204
    assert (await mine.get("/v1/staff/work-off-templates")).json() == []


async def test_empty_template_text_is_422(
    env: Env, http_client: HttpClientFactory
) -> None:
    """WO-1: invalid text is a validation problem."""
    client = await client_as(http_client, env, env.teacher)

    response = await client.post("/v1/staff/work-off-templates", json={"text": " "})

    assert response.status_code == 422
    assert response.json()["type"] == "work-off/text-invalid"


# - - - Attendance with work-offs - - -


async def test_submit_per_student_common_and_none_modes(
    env: Env, http_client: HttpClientFactory
) -> None:
    """WO-3: each mode, the sheet carries ``work_offs``."""
    w = env.world
    client = await client_as(http_client, env, env.teacher)
    tpl = (
        await client.post("/v1/staff/work-off-templates", json={"text": "Redo ex. 4"})
    ).json()["id"]
    per = await add_lesson(env.maker, w, day=DAY, period=1)
    common = await add_lesson(env.maker, w, day=DAY, period=2)
    none = await add_lesson(env.maker, w, day=DAY, period=3)

    sheet = await submit(
        client,
        per,
        absent=[str(w.aziz.id), str(w.bobur.id)],
        work_offs=[
            {
                "student_id": str(w.aziz.id),
                "template_id": tpl,
                "text": "p. 5",
                "due_date": "2026-10-10",
            }
        ],
    )
    sheet_common = await submit(
        client,
        common,
        absent=[str(w.aziz.id), str(w.bobur.id)],
        work_off_mode="common",
        common_work_off={"text": "Everyone: essay"},
    )
    sheet_none = await submit(
        client, none, absent=[str(w.aziz.id)], work_off_mode="none"
    )

    [item] = sheet["work_offs"]
    assert item["student_id"] == str(w.aziz.id)
    assert item["template_id"] == tpl
    assert item["status"] == "assigned"
    assert item["due_date"] == "2026-10-10"
    assert item["assigned_by"] == str(w.teacher.id)
    assert {i["text"] for i in sheet_common["work_offs"]} == {"Everyone: essay"}
    assert len(sheet_common["work_offs"]) == 2
    assert sheet_none["work_offs"] == []


async def test_submit_work_off_errors(env: Env, http_client: HttpClientFactory) -> None:
    """WO-3: not absent and missing common text are 422, foreign template 404."""
    w = env.world
    client = await client_as(http_client, env, env.teacher)
    other = await client_as(http_client, env, env.other_teacher)
    foreign = (
        await other.post("/v1/staff/work-off-templates", json={"text": "Theirs"})
    ).json()["id"]
    lesson = await add_lesson(env.maker, w, day=DAY)
    url = f"/v1/staff/lessons/{lesson}/attendance"

    not_absent = await client.put(
        url,
        json={
            "absent": [],
            "base_version": 0,
            "work_offs": [{"student_id": str(w.aziz.id), "text": "x"}],
        },
    )
    no_text = await client.put(
        url,
        json={"absent": [str(w.aziz.id)], "base_version": 0, "work_off_mode": "common"},
    )
    foreign_tpl = await client.put(
        url,
        json={
            "absent": [str(w.aziz.id)],
            "base_version": 0,
            "work_offs": [{"student_id": str(w.aziz.id), "template_id": foreign}],
        },
    )

    assert (not_absent.status_code, not_absent.json()["type"]) == (
        422,
        "work-off/not-absent",
    )
    assert (no_text.status_code, no_text.json()["type"]) == (
        422,
        "work-off/text-required",
    )
    assert (foreign_tpl.status_code, foreign_tpl.json()["type"]) == (
        404,
        "work-off/template-not-found",
    )


# - - - Work-off edit and delete - - -


async def test_patch_and_delete_work_off_authz(
    env: Env, http_client: HttpClientFactory
) -> None:
    """WO-3: the lesson teacher edits; another teacher gets 403; unknown is 404."""
    w = env.world
    teacher = await client_as(http_client, env, env.teacher)
    other = await client_as(http_client, env, env.other_teacher)
    admin = await client_as(http_client, env, env.admin)
    student = await client_as(http_client, env, env.student("aziz"))
    lesson = await add_lesson(env.maker, w, day=DAY)
    sheet = await submit(
        teacher,
        lesson,
        absent=[str(w.aziz.id)],
        work_offs=[
            {"student_id": str(w.aziz.id), "text": "Redo", "due_date": "2026-10-10"}
        ],
    )
    wid = sheet["work_offs"][0]["id"]

    done = await teacher.patch(f"/v1/staff/work-offs/{wid}", json={"status": "done"})
    kept_due = done.json()["due_date"]
    cleared = await teacher.patch(
        f"/v1/staff/work-offs/{wid}", json={"status": "assigned", "due_date": None}
    )
    foreign = await other.patch(f"/v1/staff/work-offs/{wid}", json={"text": "x"})
    foreign_delete = await other.delete(f"/v1/staff/work-offs/{wid}")
    unknown = await teacher.patch(f"/v1/staff/work-offs/{uuid4()}", json={"text": "x"})
    refused = await student.patch(f"/v1/staff/work-offs/{wid}", json={"text": "x"})
    as_admin = await admin.patch(f"/v1/staff/work-offs/{wid}", json={"text": "Admin"})
    deleted = await teacher.delete(f"/v1/staff/work-offs/{wid}")

    assert done.status_code == 200
    assert done.json()["status"] == "done"
    assert done.json()["done_at"] is not None
    assert kept_due == "2026-10-10"
    assert cleared.json()["done_at"] is None
    assert cleared.json()["due_date"] is None
    assert foreign.status_code == 403
    assert foreign_delete.status_code == 403
    assert unknown.status_code == 404
    assert unknown.json()["type"] == "work-off/not-found"
    assert refused.status_code == 403
    assert as_admin.json()["text"] == "Admin"
    assert deleted.status_code == 204


# - - - Student - - -


async def test_student_sees_only_their_own_work_offs(
    env: Env, http_client: HttpClientFactory
) -> None:
    """WO-6: ``GET /v1/me/work-offs`` filters by status and by student."""
    w = env.world
    teacher = await client_as(http_client, env, env.teacher)
    aziz = await client_as(http_client, env, env.student("aziz"))
    bobur = await client_as(http_client, env, env.student("bobur"))
    lesson = await add_lesson(env.maker, w, day=DAY)
    sheet = await submit(
        teacher,
        lesson,
        absent=[str(w.aziz.id), str(w.bobur.id)],
        work_off_mode="common",
        common_work_off={"text": "Redo"},
    )
    mine = next(i for i in sheet["work_offs"] if i["student_id"] == str(w.aziz.id))

    open_items = await aziz.get("/v1/me/work-offs")
    await teacher.patch(f"/v1/staff/work-offs/{mine['id']}", json={"status": "done"})
    still_open = await aziz.get("/v1/me/work-offs")
    everything = await aziz.get("/v1/me/work-offs", params={"status": "all"})
    bobur_items = await bobur.get("/v1/me/work-offs")
    staff_refused = await teacher.get("/v1/me/work-offs")

    [item] = open_items.json()
    assert item["id"] == mine["id"]
    assert item["subject_name"] == "Physics"
    assert item["text"] == "Redo"
    assert set(item) == {
        "id",
        "lesson_id",
        "date",
        "period",
        "subject_name",
        "teacher_name",
        "text",
        "status",
        "due_date",
        "done_at",
        "created_at",
    }
    assert still_open.json() == []
    assert [i["status"] for i in everything.json()] == ["done"]
    assert [i["id"] for i in bobur_items.json()] != [mine["id"]]
    assert len(bobur_items.json()) == 1
    assert staff_refused.status_code == 403


# - - - Administration - - -


async def test_admin_stats_and_list_and_authz(
    env: Env, http_client: HttpClientFactory
) -> None:
    """WO-8: statistics and the filtered list; teachers get 403."""
    w = env.world
    teacher = await client_as(http_client, env, env.teacher)
    admin = await client_as(http_client, env, env.admin)
    lesson = await add_lesson(env.maker, w, day=DAY)
    await submit(
        teacher,
        lesson,
        absent=[str(w.aziz.id), str(w.bobur.id)],
        work_off_mode="common",
        common_work_off={"text": "Redo"},
    )
    window = {"from": "2026-09-01", "to": "2026-12-31"}

    stats = await admin.get(
        "/v1/admin/work-offs/stats", params={"group_by": "student", **window}
    )
    listed = await admin.get(
        "/v1/admin/work-offs",
        params={"status": "open", "student_id": str(w.aziz.id), "limit": 10, **window},
    )
    refused_stats = await teacher.get("/v1/admin/work-offs/stats")
    refused_list = await teacher.get("/v1/admin/work-offs")
    bad_group = await admin.get("/v1/admin/work-offs/stats", params={"group_by": "x"})

    assert stats.status_code == 200
    body = stats.json()
    assert (body["group_by"], body["from"], body["to"]) == (
        "student",
        "2026-09-01",
        "2026-12-31",
    )
    assert body["total_open"] == 2
    assert {r["name"] for r in body["rows"]} == {"Aziz Abdullaev", "Bobur Karimov"}
    assert all(r["open_count"] == 1 and r["done_count"] == 0 for r in body["rows"])
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["student_name"] == "Aziz Abdullaev"
    assert listed.json()["items"][0]["group_name"] == "2TN2"
    assert refused_stats.status_code == 403
    assert refused_list.status_code == 403
    assert bad_group.status_code == 422

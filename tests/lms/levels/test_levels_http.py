"""Level scheme admin routes (spec 2.5).

The implementation must provide, under /v1:
  GET|POST|PATCH /admin/lms/level-schemes  (LMS_ADMIN only)
  PUT   /admin/lms/level-schemes/{id}/tiers
  POST  /admin/lms/level-schemes/{id}:activate
  GET   /admin/lms/level-schemes/{id}/preview?xp=
  PUT   /lms/courses/{id}/level-scheme      (course staff EDIT)
Registered through the ROUTERS of `app.interfaces.http.v1.lms_learning` or an
equivalent admin router the learning/http `client` fixture can mount.
Until then every route answers 404/405, which is the expected failure.
"""

from uuid import uuid4

from app.shared.actor import Actor
from tests.lms.learning.builders import add_staff
from tests.lms.learning.http.test_lms_learning_http import course_with_everything

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NAME = {"uz": "a", "ru": "b", "en": "c"}
BODY = {"name": NAME, "scope": "platform", "curve": {"kind": "quadratic", "base": 50}}


async def test_student_cannot_list_or_create_schemes(
    client: AsyncClient, caller: dict[str, Actor], student: Actor
) -> None:
    caller["actor"] = student
    assert (await client.get("/v1/admin/lms/level-schemes")).status_code == 403
    assert (
        await client.post("/v1/admin/lms/level-schemes", json=BODY)
    ).status_code == 403


async def test_admin_creates_updates_previews_and_activates(
    client: AsyncClient, caller: dict[str, Actor], lms_admin: Actor
) -> None:
    caller["actor"] = lms_admin
    created = await client.post("/v1/admin/lms/level-schemes", json=BODY)
    assert created.status_code == 201
    sid = created.json()["id"]
    assert created.json()["active"] is False

    bad = await client.put(
        f"/v1/admin/lms/level-schemes/{sid}/tiers",
        json={
            "tiers": [
                {"level_from": 2, "title": NAME, "icon": "star", "color": "#336699"}
            ]
        },
    )
    assert bad.status_code == 422

    ok = await client.put(
        f"/v1/admin/lms/level-schemes/{sid}/tiers",
        json={
            "tiers": [
                {"level_from": 1, "title": NAME, "icon": "star", "color": "#336699"}
            ]
        },
    )
    assert ok.status_code == 200

    preview = await client.get(
        f"/v1/admin/lms/level-schemes/{sid}/preview", params={"xp": 100}
    )
    assert preview.status_code == 200
    assert {"before", "after"} <= preview.json().keys()

    act = await client.post(f"/v1/admin/lms/level-schemes/{sid}:activate")
    assert act.status_code == 200 and act.json()["active"] is True
    listed = await client.get("/v1/admin/lms/level-schemes")
    assert [s["active"] for s in listed.json()["items"]].count(True) == 1


async def test_unknown_scheme_is_404(
    client: AsyncClient, caller: dict[str, Actor], lms_admin: Actor
) -> None:
    caller["actor"] = lms_admin
    r = await client.post(f"/v1/admin/lms/level-schemes/{uuid4()}:activate")
    assert r.status_code == 404
    assert r.json()["type"] != "about:blank"


async def _course_scheme(
    client: AsyncClient, caller: dict[str, Actor], admin: Actor, course_id: object
) -> str:
    caller["actor"] = admin
    r = await client.post(
        "/v1/admin/lms/level-schemes",
        json={**BODY, "scope": "course", "course_id": str(course_id)},
    )
    assert r.status_code == 201
    return str(r.json()["id"])


async def test_course_scheme_route_is_scoped_to_the_course_staff(
    client: AsyncClient,
    caller: dict[str, Actor],
    student: Actor,
    teacher: Actor,
    lms_admin: Actor,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    mine = await course_with_everything(maker)
    other = await course_with_everything(maker, slug="geometry")
    sid = await _course_scheme(client, caller, lms_admin, mine.id)
    url = f"/v1/lms/courses/{mine.id}/level-scheme"
    body = {"scheme_id": sid}
    for actor in (student, teacher):  # neither is staff
        caller["actor"] = actor
        assert (await client.put(url, json=body)).status_code == 403
    await add_staff(
        maker, other, teacher.user_id, permissions=["edit"]
    )  # another course
    assert (await client.put(url, json=body)).status_code == 403
    await add_staff(
        maker, mine, teacher.user_id, permissions=["review"]
    )  # wrong permission
    assert (await client.put(url, json=body)).status_code == 403
    r = await client.put(url, json=body)
    assert r.json()["type"] != "about:blank"


async def test_course_editor_attaches_the_scheme_of_their_own_course_only(
    client: AsyncClient,
    caller: dict[str, Actor],
    teacher: Actor,
    lms_admin: Actor,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    mine = await course_with_everything(maker)
    other = await course_with_everything(maker, slug="geometry")
    mine_scheme = await _course_scheme(client, caller, lms_admin, mine.id)
    other_scheme = await _course_scheme(client, caller, lms_admin, other.id)
    platform = (await client.post("/v1/admin/lms/level-schemes", json=BODY)).json()[
        "id"
    ]
    await add_staff(maker, mine, teacher.user_id, permissions=["edit"])
    caller["actor"] = teacher
    url = f"/v1/lms/courses/{mine.id}/level-scheme"
    assert (await client.put(url, json={"scheme_id": mine_scheme})).status_code == 200
    assert (await client.put(url, json={"scheme_id": other_scheme})).status_code in (
        403,
        404,
        422,
    )
    assert (await client.put(url, json={"scheme_id": platform})).status_code in (
        403,
        404,
        422,
    )
    assert (await client.put(url, json={"scheme_id": str(uuid4())})).status_code == 404

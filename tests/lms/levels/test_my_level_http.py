"""The learner's own level and the XP probe of the level preview."""

from app.shared.actor import Actor

from httpx import AsyncClient

NAME = {"uz": "a", "ru": "b", "en": "c"}
BODY = {"name": NAME, "scope": "platform", "curve": {"kind": "quadratic", "base": 50}}


async def test_learner_reads_their_platform_level(
    client: AsyncClient, caller: dict[str, Actor], student: Actor
) -> None:
    caller["actor"] = student
    r = await client.get("/v1/lms/me/level")
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == "platform" and body["course_id"] is None
    assert body["level"] == 1 and body["xp_total"] == 0
    assert body["tier"]["level_from"] == 1


async def test_course_scope_is_reported(
    client: AsyncClient, caller: dict[str, Actor], student: Actor
) -> None:
    caller["actor"] = student
    course_id = "00000000-0000-4000-8000-000000000001"
    r = await client.get("/v1/lms/me/level", params={"course_id": course_id})
    assert r.status_code == 200
    assert r.json()["scope"] == "course" and r.json()["course_id"] == course_id


async def test_preview_honors_the_probe_xp(
    client: AsyncClient, caller: dict[str, Actor], lms_admin: Actor
) -> None:
    caller["actor"] = lms_admin
    sid = (await client.post("/v1/admin/lms/level-schemes", json=BODY)).json()["id"]
    url = f"/v1/admin/lms/level-schemes/{sid}/preview"
    probed = await client.get(url, params={"xp": 10_000})
    assert probed.status_code == 200
    probe = probed.json()["probe"]
    assert probe["after"] > 1 and probe["before"] > 1
    assert (await client.get(url)).json()["probe"] is None

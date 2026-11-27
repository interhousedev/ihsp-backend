"""Platform badge preview and template_code on admin create."""

from app.shared.actor import Actor

from httpx import AsyncClient

PLATFORM_RULE = {"event": "level_reached", "condition": {"op": "count_gte", "value": 3}}
DESIGN = {"name": {"en": "Scholar"}, "description": {"en": "Coach"}}


async def test_preview_is_lms_admin_only(
    client: AsyncClient, caller: dict[str, Actor], student: Actor
) -> None:
    caller["actor"] = student
    r = await client.post("/v1/admin/lms/badges:preview", json={"rule": PLATFORM_RULE})
    assert r.status_code == 403


async def test_admin_previews_a_platform_rule(
    client: AsyncClient, caller: dict[str, Actor], lms_admin: Actor
) -> None:
    caller["actor"] = lms_admin
    r = await client.post("/v1/admin/lms/badges:preview", json={"rule": PLATFORM_RULE})
    assert r.status_code == 200
    body = r.json()
    assert body["would_earn"] <= body["examined"] and body["truncated"] in (True, False)


async def test_course_rule_is_refused_by_the_platform_preview(
    client: AsyncClient, caller: dict[str, Actor], lms_admin: Actor
) -> None:
    caller["actor"] = lms_admin
    rule = {"event": "step_completed", "condition": None}
    r = await client.post("/v1/admin/lms/badges:preview", json={"rule": rule})
    assert r.status_code == 422


async def test_admin_creates_a_platform_badge_from_a_template(
    client: AsyncClient, caller: dict[str, Actor], lms_admin: Actor
) -> None:
    caller["actor"] = lms_admin
    r = await client.post(
        "/v1/admin/lms/badges",
        json={
            **DESIGN,
            "template_code": "coach_scholar",
            "template_params": {"count": 7},
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["template_code"] == "coach_scholar"
    assert body["template_params"] == {"count": 7}
    assert body["rule"]["condition"]["value"] == 7


async def test_a_course_template_is_refused_for_a_platform_badge(
    client: AsyncClient, caller: dict[str, Actor], lms_admin: Actor
) -> None:
    caller["actor"] = lms_admin
    r = await client.post(
        "/v1/admin/lms/badges", json={**DESIGN, "template_code": "first_lesson"}
    )
    assert r.status_code == 422

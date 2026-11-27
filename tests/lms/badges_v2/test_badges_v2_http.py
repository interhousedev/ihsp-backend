"""Badge v2 routes (spec 2.6).

The implementation must provide, under /v1:
  GET    /lms/badge-templates                       -> {items:[{code, params, scope}]}
  (6 course+platform templates)
  POST   /lms/courses/{id}/badges:preview {rule}    -> {would_earn, sample, examined,
  total, truncated}  (staff EDIT)
  POST   /lms/courses/{id}/badges:draft {prompt}    -> draft rule + names (staff EDIT;
  AI task LMS_BADGE_DRAFT)
  GET|POST|PATCH|DELETE /admin/lms/badges           (LMS_ADMIN only, platform scope)
Existing course badge routes stay unchanged. Until implemented: 404/405.
"""

from uuid import uuid4

from app.shared.actor import Actor
from tests.lms.learning.builders import add_staff
from tests.lms.learning.http.test_lms_learning_http import course_with_everything

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

RULE = {"event": "step_completed", "condition": None}


async def test_templates_are_listed_for_any_signed_in_user(
    client: AsyncClient, caller: dict[str, Actor], teacher: Actor
) -> None:
    caller["actor"] = teacher
    r = await client.get("/v1/lms/badge-templates")
    assert r.status_code == 200
    codes = [t["code"] for t in r.json()["items"]]
    assert codes == [
        "first_lesson",
        "section_master",
        "streak_7",
        "fast_finisher",
        "comeback",
        "coach_scholar",
    ]


async def test_preview_and_draft_are_scoped_to_the_course_editors(
    client: AsyncClient,
    caller: dict[str, Actor],
    student: Actor,
    teacher: Actor,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    mine = await course_with_everything(maker)
    other = await course_with_everything(maker, slug="geometry")
    urls = [
        (f"/v1/lms/courses/{mine.id}/badges:preview", {"rule": RULE}),
        (
            f"/v1/lms/courses/{mine.id}/badges:draft",
            {"prompt": "reward the first lesson"},
        ),
    ]
    for url, body in urls:
        caller["actor"] = student
        assert (await client.post(url, json=body)).status_code == 403
        caller["actor"] = teacher
        assert (await client.post(url, json=body)).status_code == 403  # not staff
    await add_staff(
        maker, other, teacher.user_id, permissions=["edit"]
    )  # another course
    await add_staff(
        maker, mine, teacher.user_id, permissions=["review"]
    )  # wrong permission
    for url, body in urls:
        r = await client.post(url, json=body)
        assert r.status_code == 403 and r.json()["type"] != "about:blank"


async def test_course_editor_previews_with_coverage(
    client: AsyncClient,
    caller: dict[str, Actor],
    teacher: Actor,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    course = await course_with_everything(maker)
    await add_staff(maker, course, teacher.user_id, permissions=["edit"])
    caller["actor"] = teacher
    r = await client.post(
        f"/v1/lms/courses/{course.id}/badges:preview", json={"rule": RULE}
    )
    assert r.status_code == 200
    assert {"would_earn", "sample", "examined", "total", "truncated"} <= r.json().keys()


async def test_platform_badges_are_lms_admin_only(
    client: AsyncClient, caller: dict[str, Actor], teacher: Actor
) -> None:
    caller["actor"] = teacher
    assert (await client.get("/v1/admin/lms/badges")).status_code == 403
    assert (
        await client.post("/v1/admin/lms/badges", json={"rule": RULE})
    ).status_code == 403


async def test_admin_creates_a_platform_badge_with_an_aggregate_event(
    client: AsyncClient, caller: dict[str, Actor], lms_admin: Actor
) -> None:
    caller["actor"] = lms_admin
    body = {
        "name": {"uz": "a", "ru": "b", "en": "c"},
        "description": {"en": "d"},
        "design": {"icon": "star", "shape": "circle", "color": "#336699"},
        "rule": {
            "event": "level_reached",
            "condition": {"op": "count_gte", "value": 5},
        },
    }
    r = await client.post("/v1/admin/lms/badges", json=body)
    assert r.status_code == 201
    assert r.json()["scope"] == "platform" and r.json()["course_id"] is None
    bad = await client.post(
        "/v1/admin/lms/badges",
        json={
            **body,
            "rule": {
                "event": "step_completed",
                "condition": {"op": "step_is", "step_id": str(uuid4())},
            },
        },
    )
    assert bad.status_code == 422

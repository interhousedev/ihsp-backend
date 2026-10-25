"""HTTP contract and access of the lesson sources routes."""

from collections.abc import Awaitable, Callable

from app.shared.actor import Role
from tests.fakes.links.world import LinksWorld
from tests.links.unit.test_lesson_sources import G1, G2, SUBJECT, Setup

from httpx import AsyncClient

Api = Callable[..., Awaitable[AsyncClient]]
STAFF = f"/v1/staff/subjects/{SUBJECT}/lesson-sources"
ADMIN = f"/v1/admin/subjects/{SUBJECT}/lesson-sources"
HIDDEN = f"/v1/staff/subjects/{SUBJECT}/groups/{G1}/emis-sources-hidden"


async def test_routes_check_roles(world: LinksWorld, api: Api) -> None:
    """Students get 403 everywhere; teachers not on the admin route."""
    s = Setup(world)
    student = await api(world.person("Ann"))
    teacher = await api(s.teacher)
    stranger = await api(world.person("Zed", Role.TEACHER))

    assert (await student.get(STAFF)).status_code == 403
    assert (await student.get(ADMIN)).status_code == 403
    assert (await student.get(HIDDEN)).status_code == 403
    assert (await teacher.get(ADMIN)).status_code == 403
    refused = await stranger.get(STAFF)
    assert refused.status_code == 403
    assert refused.json()["type"] == "links/not-teaching-subject"
    other_group = f"/v1/staff/subjects/{SUBJECT}/groups/{G2}/emis-sources-hidden"
    other = await api(s.other)  # teaches only group 1A
    assert (await other.get(other_group)).status_code == 403


async def test_listing_and_toggle_shapes(world: LinksWorld, api: Api) -> None:
    """Item fields, the page envelope and the PUT toggle."""
    s = Setup(world)
    await s.emis(s.a_new.id, "https://e.uz/new", "New")
    teacher = await api(s.teacher)
    admin = await api(world.person("Root", Role.ADMIN))

    page = (await teacher.get(STAFF, params={"group_id": str(G1)})).json()
    assert page["total"] == 1 and page["limit"] == 50 and page["offset"] == 0
    [item] = page["items"]
    assert set(item) == {
        "link_id", "lesson_id", "group_id", "group_name", "date", "title", "name",
        "kind", "short_url", "target_url", "file", "hidden", "hidden_by_rule",
        "source",
    }  # fmt: skip
    assert item["title"] == "07.10 New" and item["source"] == "emis"
    assert (await admin.get(ADMIN, params={"origin": "all"})).json()["total"] == 1

    assert (await teacher.get(HIDDEN)).json() == {"hidden": False, "affected": 0}
    put = await teacher.put(HIDDEN, json={"hidden": True})
    assert put.status_code == 200 and put.json() == {"hidden": True, "affected": 1}
    [item] = (await teacher.get(STAFF)).json()["items"][:1]
    assert item["hidden"] and item["hidden_by_rule"]

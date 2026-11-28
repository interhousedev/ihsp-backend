"""Club directory, own state, profile fields, form fields and points rules over HTTP."""

from uuid import UUID

from app.modules.activities.domain.club import ClubCapability
from app.shared.actor import Actor, Role
from tests.activities.http.conftest import MakeClient
from tests.activities.http.test_activities_routes import _active_club
from tests.fakes.activities.world import ActivitiesWorld

A = "/v1/activities"


async def _enable(world: ActivitiesWorld, su: Actor, club_id: str) -> None:
    await world.services.clubs.set_capabilities(
        su, UUID(club_id), {ClubCapability.FORMS, ClubCapability.POINTS}
    )


async def test_directory_and_my_state(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor, student: Actor
) -> None:
    owner, other = world.add_student(), world.add_student()
    cid = await _active_club(world, make_client, owner, su)
    o, x = await make_client(owner), await make_client(other)
    await o.patch(f"{A}/clubs/{cid}", json={"category": "sport"})
    listed = (await x.get(f"{A}/clubs")).json()["items"]
    assert [r["club"]["id"] for r in listed] == [cid]
    assert listed[0]["member_count"] == 1 and listed[0]["club"]["category"] == "sport"
    assert listed[0]["my_role"] is None
    me = (await o.get(f"{A}/clubs/{cid}/me")).json()
    assert me["role"] == "owner" and me["can_edit"] and me["is_organizer"]
    st = (await x.get(f"{A}/clubs/{cid}/me")).json()
    assert st["role"] is None and not st["can_edit"] and not st["is_member"]


async def test_draft_hidden_from_directory_but_listed_for_owner(
    world: ActivitiesWorld, make_client: MakeClient, student: Actor
) -> None:
    c = await make_client(student)
    r = await c.post(f"{A}/clubs", json={"name": "Go", "slug": "go-club"})
    assert r.status_code == 201
    assert len((await c.get(f"{A}/clubs")).json()["items"]) == 1
    other = await make_client(world.add_student())
    assert (await other.get(f"{A}/clubs")).json()["items"] == []


async def test_profile_fields_owner_only(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor
) -> None:
    owner, other = world.add_student(), world.add_student()
    cid = await _active_club(world, make_client, owner, su)
    o, x = await make_client(owner), await make_client(other)
    body = {
        "goals": "g",
        "rules": "r",
        "schedule": "Mon 16:00",
        "partners": ["IHT"],
        "category": "arts",
    }
    got = (await o.patch(f"{A}/clubs/{cid}", json=body)).json()
    assert got["goals"] == "g" and got["partners"] == ["IHT"]
    assert (await x.patch(f"{A}/clubs/{cid}", json=body)).status_code == 403
    bad = await o.patch(f"{A}/clubs/{cid}", json={"partners": [" "]})
    assert bad.status_code in (400, 422)


async def test_form_fields_and_answers(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor
) -> None:
    owner, member = world.add_student(), world.add_student()
    cid = await _active_club(world, make_client, owner, su)
    await _enable(world, su, cid)
    o, m = await make_client(owner), await make_client(member)
    assert (await m.post(f"{A}/clubs/{cid}/join", json={})).status_code in (200, 201)
    fields = [
        {"key": "grade", "label": "Grade", "type": "select", "options": ["9", "10"]}
    ]
    assert (
        await m.put(f"{A}/clubs/{cid}/form-fields", json={"fields": fields})
    ).status_code == 403
    put = await o.put(f"{A}/clubs/{cid}/form-fields", json={"fields": fields})
    assert put.status_code == 200 and put.json()["fields"][0]["key"] == "grade"
    assert (await m.get(f"{A}/clubs/{cid}/form-fields")).json()["fields"][0][
        "type"
    ] == "select"
    dup = await o.put(f"{A}/clubs/{cid}/form-fields", json={"fields": fields + fields})
    assert dup.status_code in (400, 422)
    assert (
        await m.put(f"{A}/clubs/{cid}/profile", json={"answers": {"grade": "9"}})
    ).status_code == 200
    assert (await m.get(f"{A}/clubs/{cid}/form-answers")).status_code == 403
    rows = (await o.get(f"{A}/clubs/{cid}/form-answers")).json()["items"]
    assert rows[0]["user_id"] == str(member.user_id) and rows[0]["answers"] == {
        "grade": "9"
    }


async def test_points_rules_and_manual_award(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor
) -> None:
    owner, member = world.add_student(), world.add_student()
    cid = await _active_club(world, make_client, owner, su)
    await _enable(world, su, cid)
    o, m = await make_client(owner), await make_client(member)
    await m.post(f"{A}/clubs/{cid}/join", json={})
    base = (await m.get(f"{A}/clubs/{cid}/points/rules")).json()["rules"]
    assert base["attended"] == 2
    assert (
        await m.put(f"{A}/clubs/{cid}/points/rules", json={"rules": {"attended": 9}})
    ).status_code == 403
    assert (
        await o.put(f"{A}/clubs/{cid}/points/rules", json={"rules": {"nope": 1}})
    ).status_code in (400, 422)
    ok = await o.put(f"{A}/clubs/{cid}/points/rules", json={"rules": {"attended": 9}})
    assert ok.json()["rules"]["attended"] == 9
    award = {"user_id": str(member.user_id), "points": 7, "reason": "helped"}
    assert (
        await m.post(f"{A}/clubs/{cid}/points/awards", json=award)
    ).status_code == 403
    assert (
        await o.post(f"{A}/clubs/{cid}/points/awards", json=award)
    ).status_code == 201
    mine = (await m.get(f"{A}/clubs/{cid}/points/me")).json()
    assert mine["total"] == 7
    ghost = {**award, "user_id": str(world.add_student().user_id)}
    assert (await o.post(f"{A}/clubs/{cid}/points/awards", json=ghost)).status_code in (
        403,
        404,
        409,
    )


async def test_admin_roles_set_capabilities_others_denied(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor
) -> None:
    owner = world.add_student()
    cid = await _active_club(world, make_client, owner, su)
    url = f"/v1/admin/activities/clubs/{cid}/capabilities"
    body = {"capabilities": ["points"]}
    for role in (Role.ADMIN, Role.ACTIVITIES_ADMIN):
        c = await make_client(world.add_staff(role))
        assert (await c.put(url, json=body)).status_code == 200
    assert (await (await make_client(owner)).put(url, json=body)).status_code == 403


async def test_ratings_summary_for_members_not_outsiders_of_hidden_club(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor
) -> None:
    owner, member, viewer = (world.add_student() for _ in range(3))
    cid = await _active_club(world, make_client, owner, su)
    await (await make_client(member)).post(f"{A}/clubs/{cid}/join", json={})
    url = f"{A}/clubs/{cid}/ratings/summary"
    assert (await (await make_client(member)).get(url)).status_code == 200
    assert (await (await make_client(viewer)).get(url)).status_code == 200
    assert (await (await make_client(owner)).get(url)).status_code == 200
    draft = (
        await (await make_client(owner)).post(
            f"{A}/clubs", json={"name": "Hidden", "slug": "hidden", "description": "d"}
        )
    ).json()["id"]
    assert (
        await (await make_client(viewer)).get(f"{A}/clubs/{draft}/ratings/summary")
    ).status_code in (403, 404)

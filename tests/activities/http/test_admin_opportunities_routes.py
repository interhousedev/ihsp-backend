"""Admin opportunities CRUD over the ONE catalog (spec 4.14).

Admission's typed contract is kept.

POST   /v1/admin/activities/opportunities {kind, title, audience, ...} -> 201
       {id, lock_version}; audience is a list of admission|my_iht; `kind` is
       admission's OpportunityKind and is required (422 without/with an
       unknown one); the admission draft validation applies (empty title 422,
       non-https url 422).
GET    /v1/admin/activities/opportunities?include_archived= -> 200 {items:[...]}
PATCH  /v1/admin/activities/opportunities/{id} {..., lock_version} -> 200
       (stale lock_version -> 409 admission/conflict; lock_version required)
POST   /v1/admin/activities/opportunities/{id}:archive {archived} -> 200
DELETE /v1/admin/activities/opportunities/{id} -> 204; 409
       admission/catalog_in_use when a student plan or an activity event
       references it (archive instead; nothing is cascaded)
GET    /v1/activities/opportunities[/{id}] (student, my.iht surface) -> only
       audience containing my_iht, not archived; a hidden id answers 404
       (details obey the audience too)
Admins: ADMIN and ACTIVITIES_ADMIN. SU and students -> 403 problem+json on
EVERY admin route.
"""

from typing import Any

from app.shared.actor import Actor, Role
from tests.activities.http.conftest import MakeClient
from tests.fakes.activities.world import ActivitiesWorld

ADMIN = "/v1/admin/activities/opportunities"
BOTH = ["admission", "my_iht"]


def _body(**kw: Any) -> dict[str, Any]:
    return {"kind": "exam", "title": "Olympiad", "audience": BOTH, **kw}


async def test_admin_crud_and_audience_filter(
    world: ActivitiesWorld, make_client: MakeClient, student: Actor
) -> None:
    admin = world.add_staff(Role.ADMIN)
    c = await make_client(admin)
    r = await c.post(ADMIN, json=_body())
    assert r.status_code == 201, r.text
    oid, ver = r.json()["id"], r.json()["lock_version"]
    assert (
        await c.post(ADMIN, json=_body(title="SAT", audience=["admission"]))
    ).status_code == 201
    assert len((await c.get(ADMIN)).json()["items"]) == 2
    st = await make_client(student)
    seen = (await st.get("/v1/activities/opportunities")).json()["items"]
    assert [i["id"] for i in seen] == [oid]
    assert (
        await c.patch(
            f"{ADMIN}/{oid}", json=_body(title="Olympiad 2", lock_version=ver)
        )
    ).status_code == 200
    stale = await c.patch(
        f"{ADMIN}/{oid}", json=_body(title="Olympiad 3", lock_version=ver)
    )
    assert stale.status_code == 409 and stale.json()["type"] == "admission/conflict"
    assert (await c.delete(f"{ADMIN}/{oid}")).status_code == 204


async def test_validation_and_typed_kind(
    world: ActivitiesWorld, make_client: MakeClient
) -> None:
    c = await make_client(world.add_staff(Role.ACTIVITIES_ADMIN))
    assert (
        await c.post(ADMIN, json={"title": "x", "audience": BOTH})
    ).status_code == 422  # kind missing
    assert (await c.post(ADMIN, json=_body(kind="nope"))).status_code == 422
    assert (await c.post(ADMIN, json=_body(title=""))).status_code == 422
    assert (
        await c.post(ADMIN, json=_body(url="http://insecure.example"))
    ).status_code == 422


async def test_details_and_archived_obey_the_audience(
    world: ActivitiesWorld, make_client: MakeClient, student: Actor
) -> None:
    c = await make_client(world.add_staff(Role.ADMIN))
    st = await make_client(student)
    hidden = (
        await c.post(ADMIN, json=_body(title="SAT", audience=["admission"]))
    ).json()["id"]
    shown = (await c.post(ADMIN, json=_body())).json()["id"]
    assert (await st.get(f"/v1/activities/opportunities/{hidden}")).status_code == 404
    assert (await st.get(f"/v1/activities/opportunities/{shown}")).status_code == 200
    assert (
        await c.post(f"{ADMIN}/{shown}:archive", json={"archived": True})
    ).status_code == 200
    assert (await st.get(f"/v1/activities/opportunities/{shown}")).status_code == 404
    assert (await st.get("/v1/activities/opportunities")).json()["items"] == []
    assert len((await c.get(f"{ADMIN}?include_archived=true")).json()["items"]) == 2


async def test_delete_in_use_conflicts_and_keeps_the_plan(
    world: ActivitiesWorld, make_client: MakeClient, student: Actor
) -> None:
    c = await make_client(world.add_staff(Role.ADMIN))
    oid = (await c.post(ADMIN, json=_body())).json()["id"]
    world.add_student_plan(student, oid)
    r = await c.delete(f"{ADMIN}/{oid}")
    assert r.status_code == 409 and r.json()["type"] == "admission/catalog_in_use"
    assert world.plans_of(student) != []


async def test_activities_admin_allowed_and_audited(
    world: ActivitiesWorld, make_client: MakeClient
) -> None:
    c = await make_client(world.add_staff(Role.ACTIVITIES_ADMIN))
    assert (await c.post(ADMIN, json=_body())).status_code == 201
    assert "opportunity.staff_created" in {a.action for a in world.audit}


async def test_student_and_su_denied_every_admin_route(
    world: ActivitiesWorld, make_client: MakeClient, student: Actor, su: Actor
) -> None:
    oid = (
        await (await make_client(world.add_staff(Role.ADMIN))).post(ADMIN, json=_body())
    ).json()["id"]
    for who in (student, su):
        c = await make_client(who)
        calls = [
            await c.post(ADMIN, json=_body()),
            await c.get(ADMIN),
            await c.patch(f"{ADMIN}/{oid}", json=_body(lock_version=1)),
            await c.post(f"{ADMIN}/{oid}:archive", json={"archived": True}),
            await c.delete(f"{ADMIN}/{oid}"),
        ]
        for r in calls:
            assert r.status_code == 403
            assert r.headers["content-type"].startswith("application/problem+json")

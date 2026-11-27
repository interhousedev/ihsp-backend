"""Admin club list, resume and per-club analytics."""

from app.shared.actor import Actor
from tests.activities.http.conftest import MakeClient
from tests.fakes.activities.world import ActivitiesWorld

ADMIN = "/v1/admin/activities"


async def _club(
    make_client: MakeClient, owner: Actor, su: Actor, slug: str = "chess"
) -> str:
    c = await make_client(owner)
    r = await c.post(
        "/v1/activities/clubs",
        json={"name": "Chess", "slug": slug, "description": "d"},
    )
    cid = r.json()["id"]
    assert (await c.post(f"/v1/activities/clubs/{cid}:submit")).status_code == 200
    s = await make_client(su)
    ok = await s.post(f"{ADMIN}/clubs/{cid}:review", json={"approve": True})
    assert ok.status_code == 200
    return cid


async def test_list_filter_resume_and_analytics(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor, student: Actor
) -> None:
    cid = await _club(make_client, student, su)
    s = await make_client(su)
    page = (await s.get(f"{ADMIN}/clubs")).json()
    assert page["total"] == 1 and page["items"][0]["id"] == cid
    assert "owner_name" in page["items"][0] and page["items"][0]["member_count"] >= 0
    assert (await s.get(f"{ADMIN}/clubs?status=suspended")).json()["total"] == 0

    assert (await s.post(f"{ADMIN}/clubs/{cid}:resume")).status_code == 409
    sus = await s.post(f"{ADMIN}/clubs/{cid}:suspend", json={"reason": "x"})
    assert sus.status_code == 200
    assert (await s.get(f"{ADMIN}/clubs?status=suspended")).json()["total"] == 1
    assert (await s.post(f"{ADMIN}/clubs/{cid}:resume")).json()["status"] == "active"

    per = (await s.get(f"{ADMIN}/analytics")).json()["per_club"]
    assert per[0]["club_id"] == cid and per[0]["events"] == 0
    assert per[0]["attendance_rate"] is None and per[0]["avg_rating"] is None


async def test_list_and_resume_denied_for_student(
    make_client: MakeClient, student: Actor, su: Actor
) -> None:
    cid = await _club(make_client, student, su, "go-club")
    c = await make_client(student)
    assert (await c.get(f"{ADMIN}/clubs")).status_code == 403
    assert (await c.post(f"{ADMIN}/clubs/{cid}:resume")).status_code == 403

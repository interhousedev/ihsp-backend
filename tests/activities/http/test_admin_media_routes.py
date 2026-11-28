"""Admin club media: per-club limits and the moderation queue."""

from app.shared.actor import Actor
from tests.activities.http.conftest import MakeClient
from tests.activities.http.test_activities_routes import _active_club
from tests.fakes.activities.world import ActivitiesWorld

ADM = "/v1/admin/activities"


async def test_limits_set_clear_and_queue(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor
) -> None:
    owner = world.add_student()
    cid = await _active_club(world, make_client, owner, su)
    s, o = await make_client(su), await make_client(owner)
    r = await s.put(f"{ADM}/clubs/{cid}/media-limits", json={"quota_bytes": 5000})
    assert r.status_code == 200, r.text
    assert r.json()["quota_bytes"] == 5000 and r.json()["override_quota_bytes"] == 5000
    r = await s.delete(f"{ADM}/clubs/{cid}/media-limits")
    assert r.json()["override_quota_bytes"] is None
    assert (await o.put(f"{ADM}/clubs/{cid}/media-limits", json={})).status_code == 403
    q = await s.get(f"{ADM}/media", params={"state": "reported"})
    assert q.status_code == 200 and q.json()["total"] == 0

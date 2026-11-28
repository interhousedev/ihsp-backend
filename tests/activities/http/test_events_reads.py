"""Read routes of events and drafting rounds."""

from datetime import timedelta

from app.shared.actor import Actor
from tests.activities.http.conftest import MakeClient
from tests.activities.http.test_activities_routes import _active_club
from tests.fakes.activities.world import ActivitiesWorld


async def _club_with_events(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor
) -> tuple[Actor, str, list[str]]:
    owner = world.add_student()
    cid = await _active_club(world, make_client, owner, su)
    now = world.clock.now()
    o = await make_client(owner)
    ids = []
    for h in (3, 6):
        r = await o.post(
            f"/v1/activities/clubs/{cid}/events",
            json={
                "title": {"en": "Quiz"},
                "starts_at": (now + timedelta(hours=h)).isoformat(),
                "ends_at": (now + timedelta(hours=h + 1)).isoformat(),
            },
        )
        ids.append(r.json()["id"])
    await o.post(f"/v1/activities/events/{ids[0]}:publish")
    return owner, cid, ids


async def test_event_reads_hide_drafts_from_outsiders(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor, student: Actor
) -> None:
    owner, cid, (pub, draft) = await _club_with_events(world, make_client, su)
    s = await make_client(student)
    got = await s.get(f"/v1/activities/clubs/{cid}/events")
    assert [e["id"] for e in got.json()["items"]] == [pub]
    assert (await s.get(f"/v1/activities/events/{draft}")).status_code == 404
    assert (await s.get(f"/v1/activities/events/{pub}")).status_code == 200
    o = await make_client(owner)
    assert len((await o.get(f"/v1/activities/clubs/{cid}/events")).json()["items"]) == 2


async def test_my_rsvp_and_feed(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor, student: Actor
) -> None:
    _, _, (pub, _) = await _club_with_events(world, make_client, su)
    s = await make_client(student)
    assert (await s.get(f"/v1/activities/events/{pub}/rsvp")).json() is None
    await s.put(f"/v1/activities/events/{pub}/rsvp")
    assert (await s.get(f"/v1/activities/events/{pub}/rsvp")).json()[
        "status"
    ] == "going"
    feed = await s.get("/v1/activities/events")
    assert [e["id"] for e in feed.json()["items"]] == [pub]


async def test_draft_round_reads(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor, student: Actor
) -> None:
    owner, cid, (pub, _) = await _club_with_events(world, make_client, su)
    r = await (await make_client(student)).get(
        f"/v1/activities/clubs/{cid}/draft-rounds"
    )
    assert r.status_code == 409  # drafting capability is off by default
    o = await make_client(owner)
    r = await o.get(f"/v1/activities/clubs/{cid}/draft-rounds")
    assert r.status_code == 409

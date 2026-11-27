"""HTTP routes (spec 4.9, 4.10). Errors are RFC 9457 problem+json.

Routes expected:
  POST /v1/activities/clubs {name,slug,description} -> 201 {id,status:'draft'}
  POST /v1/activities/clubs/{id}:submit -> 200
  POST /v1/admin/activities/clubs/{id}:review {approve,reason} (SU) -> 200;
    plain student -> 403
  POST /v1/admin/activities/clubs/{id}:suspend {reason} (SU) -> 200
  POST /v1/admin/activities/clubs/{id}:force-transfer {to_user_id} (SU) -> 200
  GET  /v1/admin/activities/analytics (SU|ACTIVITIES_ADMIN) -> 200; student -> 403
  POST /v1/activities/clubs/{id}/join -> 200/201;
    POST /v1/activities/clubs/{id}/leave -> 200
  POST /v1/activities/clubs/{id}/transfers {to_user_id};
    POST /v1/activities/transfers/{id}:accept
  POST /v1/activities/clubs/{id}/events {...};
    PUT /v1/activities/events/{id}/rsvp -> {status: going|waitlist|requested}
  GET  /v1/activities/leaderboard -> 200 {items:[{rank,display_name,points}]}
  GET  /v1/public/clubs -> 200 {items:[{slug,name,logo_url,...}]} (no auth)
  GET  /v1/public/clubs/{slug} -> 200 | 404 (non-active/non-public)
  POST /v1/public/clubs/{slug}/contact
    {name,email,message,captcha_token,website?} -> 202;
    honeypot field `website` filled -> 202 but nothing stored;
    429 + Retry-After after 3/hour;
    400 problem on bad captcha; 404 when contact disabled
  PUT /v1/activities/me/seats/{seat_id}/public-consent {granted: bool} -> 200
    (only the seat's student; club owner/SU -> 403); a seat is on the public
    club page only with manager publish AND consent
  POST /v1/activities/clubs/{id}/courses {course_id} -> 201 pending
    (club owner or course teacher; 403 others);
  POST /v1/activities/clubs/{id}/courses/{course_id}:confirm -> 200
    (other side only, else 403/404);
  DELETE /v1/activities/clubs/{id}/courses/{course_id} -> 204 (either side);
  GET /v1/activities/clubs/{id}/courses -> active links
    (+ pending for the two parties)
"""

from datetime import timedelta

from app.shared.actor import Actor, Role
from tests.activities.http.conftest import MakeClient
from tests.fakes.activities.world import ActivitiesWorld

PUBLIC = "/v1/public/clubs"


async def _active_club(
    world: ActivitiesWorld, make_client: MakeClient, owner: Actor, su: Actor
) -> str:
    c = await make_client(owner)
    r = await c.post(
        "/v1/activities/clubs",
        json={"name": "Chess", "slug": "chess", "description": "d"},
    )
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert (await c.post(f"/v1/activities/clubs/{cid}:submit")).status_code == 200
    s = await make_client(su)
    assert (
        await s.post(
            f"/v1/admin/activities/clubs/{cid}:review",
            json={"approve": True, "reason": None},
        )
    ).status_code == 200
    return cid


async def test_create_submit_approve_persists(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor, student: Actor
) -> None:
    cid = await _active_club(world, make_client, student, su)
    got = await (await make_client(student)).get(f"/v1/activities/clubs/{cid}")
    assert got.json()["status"] == "active"


async def test_club_logo_url_is_served_to_logged_in_apps(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor, student: Actor
) -> None:
    cid = await _active_club(world, make_client, student, su)
    c = await make_client(student)
    assert (await c.get(f"/v1/activities/clubs/{cid}")).json()["logo_url"] is None
    file_id = "11111111-1111-4111-8111-111111111111"
    patched = await c.patch(
        f"/v1/activities/clubs/{cid}", json={"logo_file_id": file_id}
    )
    assert patched.status_code == 200, patched.text
    want = f"/v1/activities/clubs/{cid}/logo?v={file_id}"
    assert (await c.get(f"/v1/activities/clubs/{cid}")).json()["logo_url"] == want
    rows = (await c.get("/v1/activities/clubs")).json()["items"]
    assert [r["club"]["logo_url"] for r in rows if r["club"]["id"] == cid] == [want]
    admin = await (await make_client(su)).get("/v1/admin/activities/clubs")
    assert [r["logo_url"] for r in admin.json()["items"] if r["id"] == cid] == [want]


async def test_student_cannot_review(
    world: ActivitiesWorld, make_client: MakeClient, student: Actor
) -> None:
    c = await make_client(student)
    r = await c.post(
        "/v1/activities/clubs",
        json={"name": "Go", "slug": "go-club", "description": "d"},
    )
    cid = r.json()["id"]
    bad = await c.post(
        f"/v1/admin/activities/clubs/{cid}:review",
        json={"approve": True, "reason": None},
    )
    assert bad.status_code == 403
    assert bad.headers["content-type"].startswith("application/problem+json")


async def test_analytics_authz(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor, student: Actor
) -> None:
    assert (
        await (await make_client(student)).get("/v1/admin/activities/analytics")
    ).status_code == 403
    assert (
        await (await make_client(su)).get("/v1/admin/activities/analytics")
    ).status_code == 200
    admin = world.add_staff(Role.ACTIVITIES_ADMIN)
    assert (
        await (await make_client(admin)).get("/v1/admin/activities/analytics")
    ).status_code == 200


async def test_unauthenticated_is_401(make_client: MakeClient) -> None:
    assert (
        await (await make_client(None)).get("/v1/activities/leaderboard")
    ).status_code == 401


async def test_join_leave_and_unknown_club_404(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor, student: Actor
) -> None:
    owner = world.add_student()
    cid = await _active_club(world, make_client, owner, su)
    c = await make_client(student)
    assert (await c.post(f"/v1/activities/clubs/{cid}/join", json={})).status_code in (
        200,
        201,
    )
    assert (await c.post(f"/v1/activities/clubs/{cid}/leave")).status_code == 200
    ghost = "00000000-0000-4000-8000-000000000000"
    assert (
        await c.post(f"/v1/activities/clubs/{ghost}/join", json={})
    ).status_code == 404


async def test_transfer_accept_over_http(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor
) -> None:
    owner, heir = world.add_student(), world.add_student()
    cid = await _active_club(world, make_client, owner, su)
    h = await make_client(heir)
    await h.post(f"/v1/activities/clubs/{cid}/join", json={})
    o = await make_client(owner)
    await o.post(f"/v1/activities/clubs/{cid}/members/{heir.user_id}:approve")
    t = await o.post(
        f"/v1/activities/clubs/{cid}/transfers", json={"to_user_id": str(heir.user_id)}
    )
    assert t.status_code == 201
    tid = t.json()["id"]
    assert (await o.post(f"/v1/activities/transfers/{tid}:accept")).status_code == 403
    assert (await h.post(f"/v1/activities/transfers/{tid}:accept")).status_code == 200
    assert (await h.get(f"/v1/activities/clubs/{cid}")).json()["owner_id"] == str(
        heir.user_id
    )


async def test_event_rsvp_over_http(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor, student: Actor
) -> None:
    owner = world.add_student()
    cid = await _active_club(world, make_client, owner, su)
    now = world.clock.now()
    o = await make_client(owner)
    r = await o.post(
        f"/v1/activities/clubs/{cid}/events",
        json={
            "title": {"en": "Quiz"},
            "starts_at": (now + timedelta(hours=3)).isoformat(),
            "ends_at": (now + timedelta(hours=5)).isoformat(),
            "capacity": 5,
            "rsvp_policy": "open",
        },
    )
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    await o.post(f"/v1/activities/events/{eid}:publish")
    rs = await (await make_client(student)).put(f"/v1/activities/events/{eid}/rsvp")
    assert rs.status_code in (200, 201) and rs.json()["status"] == "going"


async def test_leaderboard_shape(
    world: ActivitiesWorld, make_client: MakeClient, student: Actor
) -> None:
    r = await (await make_client(student)).get("/v1/activities/leaderboard")
    assert r.status_code == 200 and isinstance(r.json()["items"], list)


# ---- public -------------------------------------------------------------------


async def test_public_listing_needs_no_auth_and_hides_drafts(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor
) -> None:
    owner = world.add_student()
    await _active_club(world, make_client, owner, su)
    await (await make_client(owner)).post(
        "/v1/activities/clubs", json={"name": "Hid", "slug": "hid", "description": "d"}
    )
    anon = await make_client(None)
    r = await anon.get(PUBLIC)
    assert r.status_code == 200
    assert [i["slug"] for i in r.json()["items"]] == ["chess"]
    assert (await anon.get(f"{PUBLIC}/hid")).status_code == 404
    assert (await anon.get(f"{PUBLIC}/chess")).status_code == 200


async def test_public_payload_leaks_no_private_fields(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor
) -> None:
    owner = world.add_student()
    await _active_club(world, make_client, owner, su)
    body = (await (await make_client(None)).get(f"{PUBLIC}/chess")).text
    assert str(owner.user_id) not in body and "email" not in body.lower()


async def _contact_club(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor
) -> None:
    owner = world.add_student()
    world.relay.reachable_ids.add(owner.user_id)  # the owner linked Telegram
    cid = await _active_club(world, make_client, owner, su)
    r = await (await make_client(owner)).patch(
        f"/v1/activities/clubs/{cid}", json={"contact_enabled": True}
    )
    assert r.status_code == 200, r.text


PAYLOAD = {
    "name": "Vera",
    "email": "v@example.com",
    "message": "Hi",
    "captcha_token": "ok",
}


async def test_contact_accepts_then_rate_limits(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor
) -> None:
    await _contact_club(world, make_client, su)
    anon = await make_client(None)
    for _ in range(3):
        assert (
            await anon.post(f"{PUBLIC}/chess/contact", json=PAYLOAD)
        ).status_code == 202
    r = await anon.post(f"{PUBLIC}/chess/contact", json=PAYLOAD)
    assert r.status_code == 429 and "retry-after" in r.headers


async def test_contact_honeypot_looks_successful(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor
) -> None:
    await _contact_club(world, make_client, su)
    r = await (await make_client(None)).post(
        f"{PUBLIC}/chess/contact", json={**PAYLOAD, "website": "x"}
    )
    assert r.status_code == 202


async def test_contact_bad_captcha_and_closed_club(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor
) -> None:
    owner = world.add_student()
    await _active_club(world, make_client, owner, su)
    anon = await make_client(None)
    assert (
        await anon.post(f"{PUBLIC}/chess/contact", json=PAYLOAD)
    ).status_code == 404  # disabled
    await (await make_client(owner)).patch(
        f"/v1/activities/clubs/{(await anon.get(f'{PUBLIC}/chess')).json()['id']}",
        json={"contact_enabled": True},
    )
    world.captcha.ok = False
    assert (await anon.post(f"{PUBLIC}/chess/contact", json=PAYLOAD)).status_code == 400


async def test_contact_validation(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor
) -> None:
    await _contact_club(world, make_client, su)
    anon = await make_client(None)
    assert (
        await anon.post(f"{PUBLIC}/chess/contact", json={**PAYLOAD, "email": "bad"})
    ).status_code == 422
    assert (
        await anon.post(
            f"{PUBLIC}/chess/contact", json={**PAYLOAD, "message": "x" * 2001}
        )
    ).status_code == 422


async def test_public_team_shows_only_consenting_published_seats_and_no_private_fields(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor
) -> None:
    owner, a, b = world.add_student(), world.add_student(), world.add_student()
    cid = await _active_club(world, make_client, owner, su)
    seat_a = world.add_team_seat(
        cid,
        a,
        position="Captain",
        bio="Chess nerd",
        photo_url="https://x/a.jpg",
        public=True,
        consent=True,
    )
    world.add_team_seat(
        cid,
        b,
        position="Treasurer",
        bio="secret bio",
        photo_url="https://x/b.jpg",
        public=True,
        consent=False,
    )  # published by the manager, no consent
    page = await (await make_client(None)).get(f"{PUBLIC}/chess")
    team = page.json()["team"]
    assert [m["position"] for m in team] == ["Captain"]
    body = page.text
    for leak in (
        str(a.user_id),
        str(b.user_id),
        "secret bio",
        "x/b.jpg",
        "email",
        str(seat_a.id),
    ):
        assert leak not in body
    # consent withdrawn -> the seat disappears at once
    assert (
        await (await make_client(a)).put(
            f"/v1/activities/me/seats/{seat_a.id}/public-consent",
            json={"granted": False},
        )
    ).status_code == 200
    assert (await (await make_client(None)).get(f"{PUBLIC}/chess")).json()["team"] == []


async def test_only_the_student_sets_consent(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor
) -> None:
    owner, a = world.add_student(), world.add_student()
    cid = await _active_club(world, make_client, owner, su)
    seat = world.add_team_seat(cid, a, position="Captain", public=True, consent=False)
    for who in (owner, su):
        r = await (await make_client(who)).put(
            f"/v1/activities/me/seats/{seat.id}/public-consent", json={"granted": True}
        )
        assert r.status_code in (403, 404)
    ok = await (await make_client(a)).put(
        f"/v1/activities/me/seats/{seat.id}/public-consent", json={"granted": True}
    )
    assert ok.status_code == 200
    assert (await (await make_client(None)).get(f"{PUBLIC}/chess")).json()["team"][0][
        "position"
    ] == "Captain"


async def test_contact_message_is_not_exposed_publicly_or_to_only_relayed_to_the_owner(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor
) -> None:
    await _contact_club(world, make_client, su)
    anon = await make_client(None)
    r = await anon.post(
        f"{PUBLIC}/chess/contact", json={**PAYLOAD, "message": "PRIVATE-MSG"}
    )
    assert (
        r.status_code == 202
        and "PRIVATE-MSG" not in r.text
        and "v@example.com" not in r.text
    )
    assert "PRIVATE-MSG" not in (await anon.get(f"{PUBLIC}/chess")).text
    assert [m["body"] for m in world.relay.delivered] == ["PRIVATE-MSG"]
    assert (await anon.get("/v1/activities/me/inbox")).status_code in (401, 404)


async def test_course_link_over_http_needs_both_sides(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor
) -> None:
    owner, stranger = world.add_student(), world.add_student()
    teacher = world.add_teacher()
    course = world.add_course(teacher=teacher)
    cid = await _active_club(world, make_client, owner, su)
    o, t = await make_client(owner), await make_client(teacher)
    assert (
        await (await make_client(stranger)).post(
            f"/v1/activities/clubs/{cid}/courses", json={"course_id": str(course.id)}
        )
    ).status_code == 403
    r = await o.post(
        f"/v1/activities/clubs/{cid}/courses", json={"course_id": str(course.id)}
    )
    assert r.status_code == 201 and r.json()["status"] == "pending"
    assert (
        await o.post(f"/v1/activities/clubs/{cid}/courses/{course.id}:confirm")
    ).status_code in (403, 404)
    assert (
        await t.post(f"/v1/activities/clubs/{cid}/courses/{course.id}:confirm")
    ).status_code == 200
    got = await o.get(f"/v1/activities/clubs/{cid}/courses")
    assert [x["course_id"] for x in got.json()["items"]] == [str(course.id)]
    assert (
        await t.delete(f"/v1/activities/clubs/{cid}/courses/{course.id}")
    ).status_code == 204


class _FakePublicFiles:
    @staticmethod
    async def read_bytes(file_id: object) -> bytes:
        return b"\x89PNG\r\n\x1a\nfake"


class _FakeFiles:
    public = _FakePublicFiles()


async def test_club_logo_is_anonymous_for_active_and_404_for_draft(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor, student: Actor
) -> None:
    cid = await _active_club(world, make_client, student, su)
    c = await make_client(student)
    file_id = "11111111-1111-4111-8111-111111111111"
    await c.patch(f"/v1/activities/clubs/{cid}", json={"logo_file_id": file_id})
    draft = (
        await c.post(
            "/v1/activities/clubs",
            json={"name": "Go", "slug": "go-club", "description": "d"},
        )
    ).json()["id"]
    await c.patch(f"/v1/activities/clubs/{draft}", json={"logo_file_id": file_id})
    anon = await make_client()
    anon_app = anon._transport.app  # type: ignore[attr-defined]
    anon_app.state.container.files = _FakeFiles()
    ok = await anon.get(f"/v1/activities/clubs/{cid}/logo?v={file_id}")
    assert ok.status_code == 200
    assert ok.headers["cache-control"] == "public, max-age=86400"
    assert ok.headers["content-type"] == "image/png"
    assert (await anon.get(f"/v1/activities/clubs/{draft}/logo")).status_code == 404

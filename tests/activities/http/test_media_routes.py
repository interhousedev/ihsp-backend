"""Club media over HTTP: upload matrix and the signed file route."""

import base64
import hashlib

from app.shared.actor import Actor
from tests.activities.http.conftest import MakeClient
from tests.activities.http.test_activities_routes import _active_club
from tests.fakes.activities.world import ActivitiesWorld

A = "/v1/activities"


def _body(n: int, **kw: object) -> dict[str, object]:
    sha = base64.b64encode(hashlib.sha256(str(n).encode()).digest()).decode()
    body = {
        "name": f"p{n}.jpg",
        "size": 100,
        "content_type": "image/jpeg",
        "sha256_b64": sha,
        "consent_attested": True,
    }
    return {**body, **kw}


async def test_upload_matrix_and_signed_route(
    world: ActivitiesWorld, make_client: MakeClient, su: Actor
) -> None:
    owner, other = world.add_student(), world.add_student()
    cid = await _active_club(world, make_client, owner, su)
    o, x = await make_client(owner), await make_client(other)
    assert (
        await x.post(f"{A}/clubs/{cid}/media:request-upload", json=_body(1))
    ).status_code == 403
    r = await o.post(
        f"{A}/clubs/{cid}/media:request-upload",
        json=_body(1, content_type="text/plain"),
    )
    assert r.status_code == 415
    r = await o.post(
        f"{A}/clubs/{cid}/media:request-upload", json=_body(1, size=10_000)
    )
    assert r.status_code == 413
    r = await o.post(
        f"{A}/clubs/{cid}/media:request-upload", json=_body(1, consent_attested=False)
    )
    assert r.status_code == 422
    album = (await o.post(f"{A}/clubs/{cid}/albums", json={"title": "Trip"})).json()
    r = await o.post(
        f"{A}/clubs/{cid}/media:request-upload", json=_body(1, album_id=album["id"])
    )
    assert r.status_code == 201, r.text
    mid = r.json()["media"]["id"]
    assert r.json()["upload"]["method"] == "PUT"
    assert (await o.post(f"{A}/media/{mid}:complete")).status_code == 200
    await world.services.media.process(__import__("uuid").UUID(mid))
    item = (await x.get(f"{A}/albums/{album['id']}/media")).json()["items"][0]
    thumb = item["thumb_url"]
    anon = await make_client()
    got = await anon.get(thumb)
    assert got.status_code == 200
    assert got.headers["cache-control"] == "private, max-age=600"
    assert "x-accel-expires" not in got.headers
    assert (await anon.get(thumb[:-4] + "0000")).status_code == 404
    assert (await anon.get(thumb.replace("/thumb", "/bogus"))).status_code == 404
    orig = await anon.get(item["original_url"])
    assert orig.status_code == 302
    r = await x.post(
        f"{A}/media/{mid}:report", json={"reason": "me", "is_subject": True}
    )
    assert r.status_code == 204
    assert (
        await x.post(f"{A}/media/{mid}:report", json={"reason": "me"})
    ).status_code in (404, 409)
    assert (await anon.get(thumb)).status_code == 404

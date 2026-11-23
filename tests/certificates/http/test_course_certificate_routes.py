"""HTTP on PostgreSQL: staff settings, uploads, learner status, public verify."""

import io
from collections.abc import Callable
from uuid import UUID

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.course_certificates import ROUTERS, public_limit_key
from app.modules.certificates.application.course_certificates import (
    CourseCertificates,
)
from app.modules.certificates.infrastructure import course_render
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.certificates.course_world import LABEL, Facts, make_world
from tests.conftest import HttpClientFactory

import pytest
from fastapi import Request
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

P = "/v1/certificates/courses"

World = tuple[CourseCertificates, Facts]


@pytest.fixture
def world(sessionmaker_in_tx: async_sessionmaker[AsyncSession]) -> World:
    """The service on the test transaction."""
    return make_world(sessionmaker_in_tx)


async def _client(
    http_client: HttpClientFactory,
    make_actor: Callable[..., Actor],
    world: World,
    user_id: UUID | None,
) -> AsyncClient:
    """A client signed in as ``user_id`` (None: anonymous)."""
    overrides = None
    if user_id is not None:
        actor = make_actor(Role.TEACHER, user_id=user_id)
        overrides = {get_actor: lambda: actor}
    return await http_client(ROUTERS, overrides, course_certificates=world[0])


SETTINGS = {
    "enabled": True,
    "passing_pct": 60,
    "tiers": [{"key": "normal", "label": LABEL}],
}


async def test_staff_settings_round_trip(
    http_client: HttpClientFactory, make_actor: Callable[..., Actor], world: World
) -> None:
    """Defaults first; a stored value comes back the same."""
    facts = world[1]
    staff = await _client(http_client, make_actor, world, facts.manager)

    before = await staff.get(f"{P}/{facts.course_id}/settings")
    put = await staff.put(f"{P}/{facts.course_id}/settings", json=SETTINGS)
    after = await staff.get(f"{P}/{facts.course_id}/settings")

    assert before.status_code == 200 and before.json()["enabled"] is False
    assert put.status_code == 200
    body = after.json()
    assert body["enabled"] is True and body["passing_pct"] == 60
    assert body["tiers"][0]["key"] == "normal"
    assert body["tiers"][0]["label"] == LABEL


async def test_template_upload_rejects_a_bad_file(
    http_client: HttpClientFactory, make_actor: Callable[..., Actor], world: World
) -> None:
    """A PDF header on garbage is refused; the template keeps no background."""
    facts = world[1]
    staff = await _client(http_client, make_actor, world, facts.manager)
    created = await staff.post(f"{P}/{facts.course_id}/templates", json={"name": "T"})
    template_id = created.json()["id"]

    upload = await staff.post(
        f"{P}/{facts.course_id}/templates/{template_id}/background",
        files={"file": ("cert.pdf", b"%PDF-1.4 not really", "application/pdf")},
    )
    listed = await staff.get(f"{P}/{facts.course_id}/templates")

    assert created.status_code == 200
    assert upload.status_code == 422
    assert upload.json()["type"] == "course_certificate_upload_rejected"
    assert listed.json()["items"][0]["background_url"] is None


async def test_learner_mine_issues_and_public_verify_shows_status(
    http_client: HttpClientFactory, make_actor: Callable[..., Actor], world: World
) -> None:
    """Passing learner gets a certificate; verify says valid, then revoked."""
    facts = world[1]
    learner = new_id()
    facts.results = {learner: (2, 70)}
    staff = await _client(http_client, make_actor, world, facts.manager)
    me = await _client(http_client, make_actor, world, learner)
    guest = await _client(http_client, make_actor, world, None)
    await staff.put(f"{P}/{facts.course_id}/settings", json=SETTINGS)

    mine = await me.post(f"{P}/{facts.course_id}/mine")
    assert mine.status_code == 200
    status = mine.json()
    assert status["eligible"] is True and status["passing_pct"] == 60
    certificate = status["certificate"]
    assert certificate["tier"] == LABEL and certificate["revoked"] is False
    code = certificate["code"]
    again = await me.post(f"{P}/{facts.course_id}/mine")
    assert again.json()["certificate"]["code"] == code

    valid = await guest.get(f"/v1/certificates/verify/{code.lower()}")
    assert valid.status_code == 200
    body = valid.json()
    assert body["status"] == "valid" and body["holder_name"] == "Oʻgʻiloy Qahhorova"
    assert body["course_title"] == "Physics 10" and body["tier_label"] == LABEL
    assert set(body) == {
        "status",
        "holder_name",
        "course_title",
        "tier_label",
        "partner",
        "issued_at",
        "qr_svg_url",
    }

    revoke = await staff.post(
        f"{P}/{facts.course_id}/issued/{certificate['id']}/revoke",
        json={"reason": "Plagiarism"},
    )
    revoked = await guest.get(f"/v1/certificates/verify/{code}")
    missing = await guest.get("/v1/certificates/verify/NOPE00000000")
    mine_after = await me.post(f"{P}/{facts.course_id}/mine")

    assert revoke.status_code == 204
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
    assert missing.status_code == 404
    assert mine_after.json()["certificate"]["revoked"] is True


async def test_non_staff_gets_403(
    http_client: HttpClientFactory, make_actor: Callable[..., Actor], world: World
) -> None:
    """Someone who cannot edit the course is refused every staff route."""
    facts = world[1]
    other = await _client(http_client, make_actor, world, new_id())

    responses = [
        await other.get(f"{P}/{facts.course_id}/settings"),
        await other.put(f"{P}/{facts.course_id}/settings", json=SETTINGS),
        await other.post(f"{P}/{facts.course_id}/templates", json={"name": "T"}),
        await other.get(f"{P}/{facts.course_id}/issued"),
        await other.post(f"{P}/{facts.course_id}/issue-eligible"),
    ]

    assert [r.status_code for r in responses] == [403] * 5
    assert responses[0].json()["type"] == "course_certificate_forbidden"


async def test_public_verify_is_rate_limited(
    http_client: HttpClientFactory, make_actor: Callable[..., Actor], world: World
) -> None:
    """Over 60 lookups a minute from one address answer 429."""
    guest = await _client(http_client, make_actor, world, None)

    codes = [
        (await guest.get("/v1/certificates/verify/NOPE00000000")).status_code
        for _ in range(61)
    ]

    assert codes[:60] == [404] * 60 and codes[60] == 429


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 280), "#336699").save(buffer, format="PNG")
    return buffer.getvalue()


def test_public_limit_key_never_shares_an_unknown_bucket() -> None:
    """Without a client address each connection gets its own key."""

    async def receive_a() -> dict[str, object]:
        return {}

    async def receive_b() -> dict[str, object]:
        return {}

    scope: dict[str, object] = {"type": "http", "client": None, "headers": []}
    first = public_limit_key(None, Request(scope, receive_a))
    second = public_limit_key(None, Request(scope, receive_b))

    assert first != second
    assert "unknown" not in first and "unknown" not in second
    assert public_limit_key("10.0.0.1", Request(scope, receive_a)).endswith(":10.0.0.1")


async def test_public_assets_need_a_public_course_with_certificates_on(
    http_client: HttpClientFactory, make_actor: Callable[..., Actor], world: World
) -> None:
    """Logo and background by bare id: 404 until public and enabled."""
    facts = world[1]
    staff = await _client(http_client, make_actor, world, facts.manager)
    guest = await _client(http_client, make_actor, world, None)
    course = f"{P}/{facts.course_id}"
    partner = await staff.post(f"{course}/partners", json={"name": "Partner"})
    partner_id = partner.json()["id"]
    logo = await staff.post(
        f"{course}/partners/{partner_id}/logo",
        files={"file": ("logo.png", _png(), "image/png")},
    )
    template = await staff.post(f"{course}/templates", json={"name": "T"})
    template_id = template.json()["id"]
    upload = await staff.post(
        f"{course}/templates/{template_id}/background",
        files={"file": ("bg.png", _png(), "image/png")},
    )
    assert logo.status_code == 200 and upload.status_code == 200
    logo_url = logo.json()["logo_url"]
    background_url = upload.json()["background_url"]
    bare_logo = logo_url.split("?")[0]
    bare_background = background_url.split("?")[0]

    disabled = [
        (await guest.get(bare_logo)).status_code,
        (await guest.get(bare_background)).status_code,
    ]
    linked = [
        (await guest.get(logo_url)).status_code,
        (await guest.get(background_url)).status_code,
    ]
    await staff.put(f"{course}/settings", json=SETTINGS)
    enabled = [
        (await guest.get(bare_logo)).status_code,
        (await guest.get(bare_background)).status_code,
    ]
    facts.public = False
    private = [
        (await guest.get(bare_logo)).status_code,
        (await guest.get(bare_background)).status_code,
    ]
    wrong_version = await guest.get(f"{bare_logo}?v={new_id()}")

    assert disabled == [404, 404]
    assert linked == [200, 200]
    assert enabled == [200, 200]
    assert private == [404, 404]
    assert wrong_version.status_code == 404


async def test_sample_png_is_rendered_once_per_design(
    http_client: HttpClientFactory,
    make_actor: Callable[..., Actor],
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated sample requests reuse the render until the design changes."""
    facts = world[1]
    staff = await _client(http_client, make_actor, world, facts.manager)
    guest = await _client(http_client, make_actor, world, None)
    renders: list[int] = []
    real = course_render.to_png

    def counting(image: Image.Image, max_side: int = 1600) -> bytes:
        renders.append(1)
        return real(image, max_side)

    monkeypatch.setattr(course_render, "to_png", counting)
    course = f"{P}/{facts.course_id}"
    template = await staff.post(f"{course}/templates", json={"name": "T"})
    body = template.json()
    await staff.put(f"{course}/settings", json={**SETTINGS, "template_id": body["id"]})

    first = await guest.get(f"{course}/sample.png")
    second = await guest.get(f"{course}/sample.png")
    assert first.status_code == second.status_code == 200
    assert first.content == second.content and len(renders) == 1

    fields = [{**f, "color": "#ff0000"} for f in body["fields"]]
    await staff.put(
        f"{course}/templates/{body['id']}",
        json={"name": "T", "fields": fields, "qr": body["qr"]},
    )
    third = await guest.get(f"{course}/sample.png")

    assert third.status_code == 200 and len(renders) == 2


async def test_public_info_lists_every_partner_of_the_course(
    http_client: HttpClientFactory, make_actor: Callable[..., Actor], world: World
) -> None:
    """The course page shows all partners; co_issued only affects the certificate."""
    facts = world[1]
    staff = await _client(http_client, make_actor, world, facts.manager)
    guest = await _client(http_client, make_actor, world, None)
    course = f"{P}/{facts.course_id}"
    await staff.post(f"{course}/partners", json={"name": "Co", "co_issued": True})
    await staff.post(f"{course}/partners", json={"name": "Host", "co_issued": False})

    info = await guest.get(f"{course}/public")

    assert info.status_code == 200
    assert sorted(p["name"] for p in info.json()["partners"]) == ["Co", "Host"]

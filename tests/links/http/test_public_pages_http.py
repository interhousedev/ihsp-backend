"""HTTP behaviour of the public hosts: short links, room pages, robots.txt."""

from collections.abc import Awaitable, Callable

from app.modules.links.domain.link import LinkKind
from app.shared.actor import Role
from tests.fakes.links.world import LinksWorld

from httpx import AsyncClient

Api = Callable[..., Awaitable[AsyncClient]]
HostApi = Callable[[], Awaitable[AsyncClient]]
PUBLIC_HEADERS = {
    "x-robots-tag": "noindex",
    "referrer-policy": "no-referrer",
    "cache-control": "no-store",
}


def _has_public_headers(headers: dict[str, str]) -> bool:
    return all(headers.get(name) == value for name, value in PUBLIC_HEADERS.items())


async def _make_link(world: LinksWorld, url: str) -> str:
    ann = world.people.get("Ann") or world.person("Ann")
    view = await world.services.create_link.execute(
        ann, kind=LinkKind.URL, target_url=url
    )
    return view.link.slug


async def test_allowlisted_short_link_is_a_302_with_safe_headers(
    world: LinksWorld, api: Api
) -> None:
    """SL-4, UF-PUB-03: 302 redirect, noindex, no referrer."""
    slug = await _make_link(world, "https://en.wikipedia.org/wiki/Physics")
    client = await api(None)

    response = await client.get(f"/s/{slug}")

    assert response.status_code == 302
    assert response.headers["location"] == "https://en.wikipedia.org/wiki/Physics"
    assert _has_public_headers(dict(response.headers))


async def test_unknown_domain_shows_the_interstitial_html(
    world: LinksWorld, api: Api
) -> None:
    """SL-4: the full destination with Continue and Report."""
    slug = await _make_link(world, "https://example.org/page")
    client = await api(None)

    response = await client.get(f"/s/{slug}", headers={"accept-language": "en"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "https://example.org/page" in response.text
    assert "Continue" in response.text
    assert f"/s/{slug}/report" in response.text
    assert _has_public_headers(dict(response.headers))


async def test_404_410_and_429_pages(world: LinksWorld, api: Api) -> None:
    """SL-7, SL-10: status codes and Retry-After."""
    ann = world.person("Ann")
    slug = await _make_link(world, "https://example.org/a")
    link = next(iter(world.uow.store.links.values()))
    await world.services.delete_link.execute(ann, link.id)
    client = await api(None)

    gone = await client.get(f"/s/{slug}")
    missing = await client.get("/s/zzz")
    for index in range(60):
        await client.get(f"/s/miss{index}")
    limited = await client.get("/s/another")

    assert gone.status_code == 410
    assert missing.status_code == 404
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) > 0
    assert _has_public_headers(dict(limited.headers))


async def test_host_router_serves_slugs_at_the_root(
    world: LinksWorld, host_api: HostApi
) -> None:
    """SL-4: on s.ihsu.uz the same handler answers at /{slug}."""
    slug = await _make_link(world, "https://en.wikipedia.org/wiki/Physics")
    client = await host_api()

    redirect = await client.get(f"/{slug}")
    robots = await client.get("/robots.txt")
    favicon = await client.get("/favicon.ico")

    assert redirect.status_code == 302
    assert robots.status_code == 200
    assert robots.text == "User-agent: *\nDisallow: /\n"
    assert favicon.status_code == 404


async def test_html_report_form_round_trip(world: LinksWorld, api: Api) -> None:
    """SL-9, UF-PUB-05: GET the form, POST it as a browser would."""
    slug = await _make_link(world, "https://example.org/a")
    client = await api(None)

    form = await client.get(f"/s/{slug}/report", headers={"accept-language": "en"})
    sent = await client.post(
        f"/s/{slug}/report",
        data={"reason": "phishing", "comment": "fake login"},
        headers={"accept-language": "en"},
    )

    assert form.status_code == 200
    assert 'method="post"' in form.text
    assert sent.status_code == 202
    assert "Thank you" in sent.text
    assert next(iter(world.uow.store.links.values())).reports == 1


async def test_robots_txt_on_the_main_host(api: Api) -> None:
    """ROOM-5: robots.txt disallows everything."""
    response = await (await api(None)).get("/robots.txt")

    assert response.status_code == 200
    assert "Disallow: /" in response.text


async def test_room_page_flow_with_headers(world: LinksWorld, api: Api) -> None:
    """ROOM-2, ROOM-5, UF-PUB-04: PIN form, right PIN, noindex headers."""
    teacher = world.person("Galina", Role.TEACHER, last_name="Kalandarova")
    room = world.schedule.add_room("102", pin="483920")
    world.schedule.add_lesson(teacher_id=teacher.user_id, room=room)
    client = await api(None)

    form = await client.get("/r/102", headers={"accept-language": "en"})
    wrong = await client.post("/r/102", data={"pin": "111111"})
    opened = await client.post("/r/102", data={"pin": "483920", "date": "2026-10-06"})
    page = await client.get("/r/102")  # the client keeps the session cookie
    missing = await client.get("/r/999")

    assert form.status_code == 200 and 'name="pin"' in form.text
    assert 'method="post"' in form.text
    assert wrong.status_code == 403
    assert opened.status_code == 303
    assert opened.headers["location"] == "/r/102?date=2026-10-06"
    cookie = opened.headers["set-cookie"]
    assert cookie.startswith("room_session=")
    assert "HttpOnly" in cookie and "Path=/r/102" in cookie and "SameSite=lax" in cookie
    assert "483920" not in cookie
    assert page.status_code == 200
    assert "Physics" in page.text and "Kalandarova G." in page.text
    assert "483920" not in page.text
    assert missing.status_code == 404
    for response in (form, wrong, opened, page, missing):
        assert _has_public_headers(dict(response.headers))


async def test_a_legacy_pin_query_is_redirected_away_at_once(
    world: LinksWorld, api: Api
) -> None:
    """ROOM-2: `?pin=` printed on a door still works but leaves the address bar."""
    room = world.schedule.add_room("102", pin="483920")
    world.schedule.add_lesson(room=room)
    client = await api(None)

    response = await client.get("/r/102", params={"pin": "483920"})

    assert response.status_code == 303
    assert response.headers["location"] == "/r/102"
    assert "room_session=" in response.headers["set-cookie"]


async def test_room_pin_lockout_over_http(world: LinksWorld, api: Api) -> None:
    """ROOM-5: five wrong PINs, then 429 with Retry-After."""
    world.schedule.add_room("102", pin="483920")
    client = await api(None)
    for _ in range(5):
        assert (await client.post("/r/102", data={"pin": "000000"})).status_code == 403

    response = await client.post("/r/102", data={"pin": "483920"})

    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0

"""LIB-12: HTTP routes of the UniLibrary administration."""

from collections.abc import Awaitable, Callable
from dataclasses import replace

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.library import external as external_routes
from app.modules.library.wiring import LibraryServices
from app.modules.library.wiring_external import ExternalServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.conftest import HttpClientFactory
from tests.fakes.library.academic import FakeAcademicDirectory
from tests.fakes.library.external_catalog import FakeExternalCatalog

import pytest
from httpx import AsyncClient

ADMIN = "/v1/admin/library/unilibrary"
Api = Callable[[Actor | None], Awaitable[AsyncClient]]
FEED = {
    "name": "Physics textbooks",
    "params": {
        "category": 1,
        "field_ids": [27],
        "type_ids": [9, 2],
        "language_ids": [2, 26],
        "access": ["open", "partial"],
    },
    "max_items": 500,
}


@pytest.fixture
def api(
    http_client: HttpClientFactory,
    library: LibraryServices,
    external_off: ExternalServices,
) -> Api:
    """A client for the admin routes with UniLibrary off (as shipped)."""

    async def build(actor: Actor | None = None) -> AsyncClient:
        overrides = {get_actor: (lambda: actor)} if actor else None
        services = replace(library, external=external_off)
        return await http_client(external_routes.ROUTERS, overrides, library=services)

    return build


# - - - Authorization - - -


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/settings"),
        ("PUT", "/settings"),
        ("GET", "/feeds"),
        ("POST", "/feeds"),
        ("GET", "/field-map"),
        ("PUT", "/field-map"),
        ("GET", "/status"),
    ],
)
async def test_only_administration_may_use_the_admin_routes(
    api: Api,
    student: Actor,
    teacher: Actor,
    librarian: Actor,
    admin: Actor,
    method: str,
    path: str,
) -> None:
    """LIB-12: students, teachers and librarians get `403`, visitors `401`."""
    bodies: dict[str, object] = {
        "/settings": {"enabled": True, "anonymous_cards": False},
        "/feeds": FEED,
        "/field-map": [],
    }
    body = bodies.get(path)

    for actor in (student, teacher, librarian):
        client = await api(actor)
        response = await client.request(method, f"{ADMIN}{path}", json=body)
        assert response.status_code == 403, (actor.roles, path)
    anonymous = await (await api(None)).request(method, f"{ADMIN}{path}", json=body)
    assert anonymous.status_code == 401
    ok = await (await api(admin)).request(method, f"{ADMIN}{path}", json=body)
    assert ok.status_code in (200, 201)


# - - - Settings - - -


async def test_settings_are_off_by_default_and_can_be_switched_on(
    api: Api, admin: Actor
) -> None:
    """LIB-12: `{enabled, anonymous_cards}`; the PUT is effective at once."""
    client = await api(admin)

    before = await client.get(f"{ADMIN}/settings")
    put = await client.put(
        f"{ADMIN}/settings", json={"enabled": True, "anonymous_cards": True}
    )
    after = await client.get(f"{ADMIN}/settings")

    assert before.json() == {"enabled": False, "anonymous_cards": False}
    assert put.status_code == 200
    assert put.json() == after.json() == {"enabled": True, "anonymous_cards": True}


@pytest.mark.parametrize(
    "body", [{}, {"enabled": True}, {"enabled": "maybe", "anonymous_cards": False}]
)
async def test_settings_need_both_switches(
    api: Api, admin: Actor, body: dict[str, object]
) -> None:
    """LIB-12: a half-sent PUT is refused."""
    client = await api(admin)

    response = await client.put(f"{ADMIN}/settings", json=body)

    assert response.status_code == 422


async def test_switching_on_opens_the_user_routes(
    api: Api, admin: Actor, student: Actor, catalog: FakeExternalCatalog
) -> None:
    """LIB-12: off, `404`; after the admin PUT, `200`."""
    user = await api(student)
    assert (
        await user.get("/v1/library/external/unilibrary/taxonomies")
    ).status_code == 404

    await (await api(admin)).put(
        f"{ADMIN}/settings", json={"enabled": True, "anonymous_cards": False}
    )

    opened = await (await api(student)).get(
        "/v1/library/external/unilibrary/taxonomies"
    )
    assert opened.status_code == 200


# - - - Feeds - - -


async def test_feed_lifecycle_over_http(api: Api, admin: Actor) -> None:
    """LIB-12: create, list, patch, enable, delete."""
    client = await api(admin)

    created = await client.post(f"{ADMIN}/feeds", json=FEED)
    feed = created.json()
    listed = await client.get(f"{ADMIN}/feeds")
    patched = await client.patch(
        f"{ADMIN}/feeds/{feed['id']}", json={"name": "Physics"}
    )
    enabled = await client.post(f"{ADMIN}/feeds/{feed['id']}/enable")
    disabled = await client.post(f"{ADMIN}/feeds/{feed['id']}/disable")
    deleted = await client.delete(f"{ADMIN}/feeds/{feed['id']}")
    after = await client.get(f"{ADMIN}/feeds")

    assert created.status_code == 201
    assert feed == {
        "id": feed["id"],
        "name": "Physics textbooks",
        "enabled": False,
        "params": FEED["params"],
        "max_items": 500,
        "estimate": None,
        "last_run_at": None,
        "last_status": None,
        "last_count": None,
    }
    assert [f["id"] for f in listed.json()] == [feed["id"]]
    assert patched.json()["name"] == "Physics"
    assert patched.json()["params"] == FEED["params"]
    assert enabled.json()["enabled"] is True
    assert disabled.json()["enabled"] is False
    assert deleted.status_code == 204
    assert after.json() == []


@pytest.mark.parametrize("action", ["dry-run", "run"])
async def test_dry_run_and_run_are_409_because_the_sync_is_not_built(
    api: Api, admin: Actor, action: str
) -> None:
    """LIB-12: `library/external-sync-unavailable`."""
    client = await api(admin)
    feed = (await client.post(f"{ADMIN}/feeds", json=FEED)).json()

    response = await client.post(f"{ADMIN}/feeds/{feed['id']}/{action}")

    assert response.status_code == 409
    assert response.json()["type"] == "library/external-sync-unavailable"


async def test_unknown_feed_and_unknown_action(api: Api, admin: Actor) -> None:
    """LIB-12: `404 library/feed-not-found`; an unknown action is `422`."""
    client = await api(admin)
    feed = (await client.post(f"{ADMIN}/feeds", json=FEED)).json()
    missing = new_id()

    patch = await client.patch(f"{ADMIN}/feeds/{missing}", json={"name": "x"})
    delete = await client.delete(f"{ADMIN}/feeds/{missing}")
    action = await client.post(f"{ADMIN}/feeds/{feed['id']}/explode")

    assert patch.status_code == delete.status_code == 404
    assert patch.json()["type"] == "library/feed-not-found"
    assert action.status_code == 422


@pytest.mark.parametrize(
    "mutate",
    [
        {"name": "   "},
        {"name": "x" * 121},
        {"max_items": -1},
        {"params": {"category": 7}},
        {"params": {"category": 1, "access": ["secret"]}},
        {"params": {"category": 1, "field_ids": [0]}},
        {"params": {"category": 1, "mystery": 1}},
        {"unknown_key": 1},
    ],
)
async def test_bad_feeds_are_rejected(
    api: Api, admin: Actor, mutate: dict[str, object]
) -> None:
    """LIB-12: names, sizes and filters are validated."""
    client = await api(admin)

    response = await client.post(f"{ADMIN}/feeds", json={**FEED, **mutate})

    assert response.status_code == 422


# - - - Field map - - -


async def test_field_map_put_and_get(
    api: Api, admin: Actor, academic: FakeAcademicDirectory
) -> None:
    """LIB-12: `[{subject_id, external_field_id}]`."""
    physics = academic.add_subject(new_id(), "Physics")
    client = await api(admin)
    entries = [{"subject_id": str(physics), "external_field_id": 27}]

    put = await client.put(f"{ADMIN}/field-map", json=entries)
    got = await client.get(f"{ADMIN}/field-map")

    assert put.status_code == 200
    assert put.json() == got.json() == entries


async def test_field_map_with_an_unknown_subject_is_422(api: Api, admin: Actor) -> None:
    """LIB-12: `library/field-map-invalid` names the subjects."""
    client = await api(admin)
    ghost = str(new_id())

    response = await client.put(
        f"{ADMIN}/field-map", json=[{"subject_id": ghost, "external_field_id": 27}]
    )

    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "library/field-map-invalid"
    assert body["params"]["subject_ids"] == [ghost]


async def test_field_map_rejects_bad_entries(api: Api, admin: Actor) -> None:
    """LIB-12: ids must be UUIDs and positive numbers."""
    client = await api(admin)

    response = await client.put(
        f"{ADMIN}/field-map", json=[{"subject_id": "x", "external_field_id": 0}]
    )

    assert response.status_code == 422


# - - - Status - - -


async def test_status_answers_the_contract_shape(api: Api, admin: Actor) -> None:
    """LIB-12: `{breaker, last_calls, cache, hidden_records}`."""
    client = await api(admin)

    response = await client.get(f"{ADMIN}/status")

    assert response.status_code == 200
    assert response.json() == {
        "breaker": "closed",
        "last_calls": [],
        "cache": {"hits": 0, "misses": 0, "stale_served": 0},
        "hidden_records": [],
    }

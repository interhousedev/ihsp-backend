"""LIB-5, LIB-7, LIB-12: HTTP routes of the UniLibrary records (signed in)."""

from collections.abc import Awaitable, Callable
from dataclasses import replace

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.library import external as external_routes
from app.modules.library.wiring import LibraryServices
from app.modules.library.wiring_external import ExternalServices
from app.shared.actor import Actor
from tests.conftest import HttpClientFactory
from tests.fakes.library.external_catalog import (
    FakeExternalCatalog,
    make_detail,
    make_record,
)

import pytest
from httpx import AsyncClient

BASE = "/v1/library/external/unilibrary"
Api = Callable[[Actor | None], Awaitable[AsyncClient]]


@pytest.fixture
def api(
    http_client: HttpClientFactory, library: LibraryServices, external: ExternalServices
) -> Api:
    """`await api(actor)`: a client for the external routes, signed in as the actor."""

    async def build(actor: Actor | None = None) -> AsyncClient:
        overrides = {get_actor: (lambda: actor)} if actor else None
        services = replace(library, external=external)
        return await http_client(external_routes.ROUTERS, overrides, library=services)

    return build


@pytest.fixture
def api_off(
    http_client: HttpClientFactory,
    library: LibraryServices,
    external_off: ExternalServices,
) -> Api:
    """The same with UniLibrary switched off."""

    async def build(actor: Actor | None = None) -> AsyncClient:
        overrides = {get_actor: (lambda: actor)} if actor else None
        services = replace(library, external=external_off)
        return await http_client(external_routes.ROUTERS, overrides, library=services)

    return build


# - - - Search - - -


async def test_search_answers_the_contract_shape(
    api: Api, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-12: `{items, page, total, stale}` with unstored cards."""
    catalog.add(make_record("355186"))
    client = await api(student)

    response = await client.get(f"{BASE}/search", params={"q": "elektronika"})

    assert response.status_code == 200
    body = response.json()
    assert (body["page"], body["total"], body["stale"]) == (1, 1, False)
    (card,) = body["items"]
    assert card["id"] is None and card["slug"] is None
    assert card["kind"] == "external"
    assert card["tag"] == {"source": "unilibrary", "label": "UniLibrary"}
    assert card["external"] == {
        "source": "unilibrary",
        "external_id": "355186",
        "category": 1,
        "access": "open",
        "type_name": "Darslik",
        "field_name": "Fizika",
        "view_url": "https://unilibrary.uz/literature/355186",
        "gone": False,
    }
    assert "material" not in card and "book" not in card
    assert card["subjects"] == [] and card["has_text"] is False


async def test_search_passes_its_filters_on(
    api: Api, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-5: q, field_id, type_id, language, access and page."""
    client = await api(student)

    response = await client.get(
        f"{BASE}/search",
        params={
            "q": "fizika",
            "field_id": 27,
            "type_id": 9,
            "language": "26",
            "access": "partial",
            "page": 2,
        },
    )

    assert response.status_code == 200
    sent = catalog.search_calls[0]
    assert (sent.q, sent.field_id, sent.type_id, sent.language_id) == (
        "fizika",
        27,
        9,
        26,
    )
    assert sent.access is not None and sent.access.value == "partial"
    assert sent.page == 2


async def test_access_any_sends_no_access_filter(
    api: Api, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-5: `access=any` is the default."""
    client = await api(student)

    await client.get(f"{BASE}/search", params={"access": "any"})
    await client.get(f"{BASE}/search")

    assert [c.access for c in catalog.search_calls] == [None, None]


@pytest.mark.parametrize(
    "params", [{"access": "secret"}, {"page": 0}, {"field_id": 0}, {"subject_id": "x"}]
)
async def test_bad_search_parameters_are_rejected(
    api: Api, student: Actor, params: dict[str, str | int]
) -> None:
    """LIB-12: validation errors are `422`."""
    client = await api(student)

    response = await client.get(f"{BASE}/search", params=params)

    assert response.status_code == 422


async def test_search_needs_a_login(api: Api) -> None:
    """LIB-12: signed-in users only."""
    client = await api(None)

    response = await client.get(f"{BASE}/search")

    assert response.status_code == 401


async def test_search_reports_an_unavailable_source_as_503(
    api: Api, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-12: `library/external-unavailable` with `params.retry_after`."""
    catalog.unavailable(60)
    client = await api(student)

    response = await client.get(f"{BASE}/search")

    assert response.status_code == 503
    body = response.json()
    assert body["type"] == "library/external-unavailable"
    assert body["params"]["retry_after"] == 60


async def test_search_limit_is_a_429_with_action_and_limit(
    api: Api, student: Actor
) -> None:
    """LIB-12: `library/rate-limited` with `{action, limit, resets_at}`."""
    client = await api(student)
    for _ in range(30):
        assert (await client.get(f"{BASE}/search")).status_code == 200

    response = await client.get(f"{BASE}/search")

    assert response.status_code == 429
    body = response.json()
    assert body["type"] == "library/rate-limited"
    assert body["params"]["action"] == "search"
    assert body["params"]["limit"] == 30


# - - - Record, pin, taxonomies - - -


async def test_record_card_and_missing_record(
    api: Api, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-12: `GET /{external_id}?category=` and its `404`."""
    catalog.add(make_record("355186"), make_detail("355186"))
    client = await api(student)

    found = await client.get(f"{BASE}/355186", params={"category": 1})
    missing = await client.get(f"{BASE}/404404")

    assert found.status_code == 200
    assert found.json()["page_count"] == 288
    assert missing.status_code == 404
    assert missing.json()["type"] == "library/not-found"


@pytest.mark.parametrize("category", [0, 5, "x"])
async def test_record_category_must_be_one_to_four(
    api: Api, student: Actor, category: str | int
) -> None:
    """LIB-12: the category picks the link, so it is checked."""
    client = await api(student)

    response = await client.get(f"{BASE}/1", params={"category": category})

    assert response.status_code == 422


async def test_fixed_paths_are_not_read_as_record_ids(
    api: Api, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-12: `/taxonomies` is the filter lists, not a record named so."""
    client = await api(student)

    response = await client.get(f"{BASE}/taxonomies")

    assert response.status_code == 200
    assert catalog.get_calls == []


async def test_pin_is_created_once_then_ok(
    api: Api, catalog: FakeExternalCatalog, student: Actor, other_student: Actor
) -> None:
    """LIB-7, LIB-12: `201` first, `200` later; the card has an id."""
    catalog.add(make_record("355186"), make_detail("355186"))
    client = await api(student)

    first = await client.post(f"{BASE}/355186/item", json={"category": 1})
    second = await client.post(f"{BASE}/355186/item", json={"category": 1})
    third = await (await api(other_student)).post(
        f"{BASE}/355186/item", json={"category": 1}
    )

    assert (first.status_code, second.status_code, third.status_code) == (201, 200, 200)
    card = first.json()
    assert card["id"] is not None and card["slug"].startswith("elektronika-")
    assert second.json()["id"] == card["id"] == third.json()["id"]
    assert card["external"]["external_id"] == "355186"


async def test_pin_of_a_missing_record_is_404(api: Api, student: Actor) -> None:
    """LIB-12: nothing to store."""
    client = await api(student)

    response = await client.post(f"{BASE}/404404/item", json={"category": 1})

    assert response.status_code == 404


@pytest.mark.parametrize("body", [{}, {"category": 9}, {"category": "x"}])
async def test_pin_body_needs_a_category_from_one_to_four(
    api: Api, student: Actor, body: dict[str, object]
) -> None:
    """LIB-12: `PinExternalBody`."""
    client = await api(student)

    response = await client.post(f"{BASE}/1/item", json=body)

    assert response.status_code == 422


async def test_taxonomies_answer_the_contract_shape(api: Api, student: Actor) -> None:
    """LIB-5: `{types, fields, languages, access}`."""
    client = await api(student)

    response = await client.get(f"{BASE}/taxonomies")

    assert response.status_code == 200
    body = response.json()
    assert body["types"][0] == {"id": 9, "name": "Darslik"}
    assert [f["id"] for f in body["fields"]] == [27, 25]
    assert body["languages"][1] == {"id": 26, "name": "Lotin"}
    assert body["access"] == [
        {"id": "any", "name": "Any access"},
        {"id": "open", "name": "Fully open"},
        {"id": "partial", "name": "Partly open"},
        {"id": "closed", "name": "By request"},
    ]


# - - - The flag - - -


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/search"),
        ("GET", "/taxonomies"),
        ("GET", "/355186"),
        ("POST", "/355186/item"),
    ],
)
async def test_every_route_is_404_while_switched_off_and_calls_nothing(
    api_off: Api,
    catalog: FakeExternalCatalog,
    student: Actor,
    method: str,
    path: str,
) -> None:
    """LIB-12: `404 library/external-disabled`; zero calls to UniLibrary."""
    catalog.add(make_record("355186"))
    client = await api_off(student)

    response = await client.request(
        method, f"{BASE}{path}", json={"category": 1} if method == "POST" else None
    )

    assert response.status_code == 404
    assert response.json()["type"] == "library/external-disabled"
    assert catalog.calls == 0

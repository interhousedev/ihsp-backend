"""HTTP: /v1/me/flashcard-sets* follows the API contract (paths, fields, errors)."""

from typing import Any
from uuid import UUID

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.flashcards import ROUTERS
from app.shared.ids import new_id
from tests.flashcards.conftest import FlashcardsHarness

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient, Response

SET_ITEM_KEYS = {
    "id",
    "title",
    "description",
    "source",
    "card_count",
    "due_today",
    "new_today",
}
SET_DETAIL_KEYS = SET_ITEM_KEYS | {"new_per_day", "reviews_per_day", "cards"}
CARD_KEYS = {"id", "position", "front", "back", "state", "due_at"}
STUDY_KEYS = {"set_id", "card", "intervals", "counts", "done_for_today"}
CARDS = [{"front": "Q1", "back": "A1"}, {"front": "Q2", "back": "A2"}]


class Api:
    """The wired module and a client whose requests run as `actor`."""

    def __init__(self, h: FlashcardsHarness, client: AsyncClient) -> None:
        """Start as the student."""
        self.h = h
        self.client = client
        self.actor = h.student

    async def request(self, method: str, url: str, **kwargs: Any) -> Response:
        """Send a request as the current actor."""
        return await self.client.request(method, url, **kwargs)

    async def create(self, title: str = "Cells", count: int = 2) -> dict[str, Any]:
        """POST /v1/me/flashcard-sets and return the body."""
        body = {"title": title, "cards": CARDS[:count]}
        response = await self.client.post("/v1/me/flashcard-sets", json=body)
        assert response.status_code == 200, response.text
        created: dict[str, Any] = response.json()
        return created


@pytest.fixture
async def api(h: FlashcardsHarness, http_client: Any) -> Api:
    """A client for the flashcards routes; `api.actor` decides who calls."""
    holder: dict[str, Api] = {}
    client = await http_client(
        ROUTERS, {get_actor: lambda: holder["api"].actor}, flashcards=h.services
    )
    holder["api"] = Api(h, client)
    return holder["api"]


def problem(response: Response, status: int, type_: str) -> None:
    """Assert an application/problem+json answer."""
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == type_


def test_the_package_exports_a_list_of_routers() -> None:
    """Every HTTP package exports ROUTERS (a list)."""
    assert isinstance(ROUTERS, list) and len(ROUTERS) == 1


def test_the_routes_are_exactly_the_contract() -> None:
    """§ API contract → Flash cards: nine routes, no more."""
    routes = {
        (method, route.path)
        for router in ROUTERS
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods or set()
    }

    assert routes == {
        ("GET", "/v1/me/flashcard-sets"),
        ("POST", "/v1/me/flashcard-sets"),
        ("GET", "/v1/me/flashcard-sets/{set_id}"),
        ("PATCH", "/v1/me/flashcard-sets/{set_id}"),
        ("DELETE", "/v1/me/flashcard-sets/{set_id}"),
        ("PUT", "/v1/me/flashcard-sets/{set_id}/cards"),
        ("GET", "/v1/me/flashcard-sets/{set_id}/study"),
        ("POST", "/v1/me/flashcards/{card_id}/review"),
        ("POST", "/v1/me/flashcard-sets/copy"),
    }


async def test_create_returns_the_detail_with_new_cards(api: Api) -> None:
    """POST /v1/me/flashcard-sets → FlashcardSetDetail (WEB-22)."""
    response = await api.client.post(
        "/v1/me/flashcard-sets",
        json={"title": " Cells ", "description": "Chapter 1", "cards": CARDS},
    )

    body = response.json()
    assert response.status_code == 200
    assert set(body) == SET_DETAIL_KEYS
    assert (body["title"], body["description"], body["source"]) == (
        "Cells",
        "Chapter 1",
        "manual",
    )
    assert (body["card_count"], body["due_today"], body["new_today"]) == (2, 0, 2)
    assert (body["new_per_day"], body["reviews_per_day"]) == (20, 200)
    assert all(set(card) == CARD_KEYS for card in body["cards"])
    assert [(c["position"], c["front"], c["state"]) for c in body["cards"]] == [
        (0, "Q1", "new"),
        (1, "Q2", "new"),
    ]
    assert body["cards"][0]["due_at"] is None
    UUID(body["id"])


async def test_list_returns_items_with_due_and_new_counts(api: Api) -> None:
    """GET /v1/me/flashcard-sets → FlashcardSetItem[] (WEB-22)."""
    older = await api.create()
    api.h.clock.advance(minutes=1)
    newer = await api.create("Other")

    response = await api.client.get("/v1/me/flashcard-sets")

    items = response.json()
    assert response.status_code == 200
    assert all(set(item) == SET_ITEM_KEYS for item in items)
    assert [item["id"] for item in items] == [newer["id"], older["id"]]
    assert (items[1]["card_count"], items[1]["due_today"], items[1]["new_today"]) == (
        2,
        0,
        2,
    )


async def test_get_returns_the_detail(api: Api) -> None:
    """GET /v1/me/flashcard-sets/{id} → FlashcardSetDetail."""
    created = await api.create()

    response = await api.client.get(f"/v1/me/flashcard-sets/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


async def test_patch_changes_the_fields_that_are_sent(api: Api) -> None:
    """PATCH /v1/me/flashcard-sets/{id}: title, description and the daily limits."""
    created = await api.create()
    url = f"/v1/me/flashcard-sets/{created['id']}"

    changed = await api.client.patch(
        url,
        json={
            "title": "Mitosis",
            "description": "Phases",
            "new_per_day": 5,
            "reviews_per_day": 50,
        },
    )
    only_limit = await api.client.patch(url, json={"new_per_day": 7})
    cleared = await api.client.patch(url, json={"description": None})

    assert changed.status_code == 200 and set(changed.json()) == SET_DETAIL_KEYS
    body = changed.json()
    assert (body["title"], body["description"]) == ("Mitosis", "Phases")
    assert (body["new_per_day"], body["reviews_per_day"]) == (5, 50)
    assert only_limit.json()["description"] == "Phases"
    assert only_limit.json()["new_per_day"] == 7
    assert (
        cleared.json()["description"] is None and cleared.json()["title"] == "Mitosis"
    )


async def test_delete_answers_204_and_the_set_is_gone(api: Api) -> None:
    """DELETE /v1/me/flashcard-sets/{id} → 204."""
    created = await api.create()
    url = f"/v1/me/flashcard-sets/{created['id']}"

    deleted = await api.client.delete(url)
    again = await api.client.get(url)

    assert deleted.status_code == 204 and deleted.content == b""
    problem(again, 404, "flashcards/set-not-found")


async def test_put_cards_saves_the_full_ordered_list(api: Api) -> None:
    """PUT /v1/me/flashcard-sets/{id}/cards: keep by id, add, reorder, delete."""
    created = await api.create()
    first, second = created["cards"]
    await api.client.post(
        f"/v1/me/flashcards/{first['id']}/review", json={"rating": "easy"}
    )

    response = await api.client.put(
        f"/v1/me/flashcard-sets/{created['id']}/cards",
        json={
            "cards": [
                {"front": "Brand new", "back": "Card"},
                {"id": first["id"], "front": "Q1 edited", "back": "A1"},
            ]
        },
    )

    body = response.json()
    assert response.status_code == 200 and set(body) == SET_DETAIL_KEYS
    assert body["card_count"] == 2
    assert [(c["position"], c["front"], c["state"]) for c in body["cards"]] == [
        (0, "Brand new", "new"),
        (1, "Q1 edited", "review"),
    ]
    assert body["cards"][1]["id"] == first["id"]
    assert second["id"] not in {c["id"] for c in body["cards"]}


async def test_study_returns_the_next_card_and_the_labels(api: Api) -> None:
    """GET /v1/me/flashcard-sets/{id}/study → StudyNext (UF-WEB-22)."""
    created = await api.create()

    response = await api.client.get(f"/v1/me/flashcard-sets/{created['id']}/study")

    body = response.json()
    assert response.status_code == 200 and set(body) == STUDY_KEYS
    assert body["set_id"] == created["id"] and body["done_for_today"] is False
    assert body["card"] == {
        "id": created["cards"][0]["id"],
        "front": "Q1",
        "back": "A1",
        "state": "new",
    }
    assert body["intervals"] == {
        "again": "1m",
        "hard": "1m",
        "medium": "10m",
        "easy": "4d",
    }
    assert body["counts"] == {"learning": 0, "review": 0, "new": 2}


async def test_review_updates_the_card_and_returns_the_next_one(api: Api) -> None:
    """POST /v1/me/flashcards/{card_id}/review → StudyNext (WEB-23)."""
    created = await api.create()
    first, second = created["cards"]

    response = await api.client.post(
        f"/v1/me/flashcards/{first['id']}/review", json={"rating": "easy"}
    )

    body = response.json()
    assert response.status_code == 200 and set(body) == STUDY_KEYS
    assert body["card"]["id"] == second["id"]
    detail = (await api.client.get(f"/v1/me/flashcard-sets/{created['id']}")).json()
    assert [c["state"] for c in detail["cards"]] == ["review", "new"]
    assert detail["cards"][0]["due_at"].endswith("Z")


async def test_the_last_review_ends_the_session(api: Api) -> None:
    """UF-WEB-22: `card` and `intervals` are null and `done_for_today` is true."""
    created = await api.create(count=1)

    response = await api.client.post(
        f"/v1/me/flashcards/{created['cards'][0]['id']}/review",
        json={"rating": "easy"},
    )

    assert response.json() == {
        "set_id": created["id"],
        "card": None,
        "intervals": None,
        "counts": {"learning": 0, "review": 0, "new": 0},
        "done_for_today": True,
    }


async def test_copy_creates_a_set_with_fresh_cards(api: Api) -> None:
    """POST /v1/me/flashcard-sets/copy → FlashcardSetDetail (SHR-5)."""
    original = await api.create("Shared")
    api.h.shares.add("abc123", "flashcard_set", UUID(original["id"]))
    api.actor = api.h.other_student

    response = await api.client.post(
        "/v1/me/flashcard-sets/copy", json={"share_slug": "abc123"}
    )

    body = response.json()
    assert response.status_code == 200 and set(body) == SET_DETAIL_KEYS
    assert body["id"] != original["id"]
    assert (body["title"], body["source"], body["card_count"]) == (
        "Shared",
        "copied",
        2,
    )
    assert {c["state"] for c in body["cards"]} == {"new"}
    mine = (await api.client.get("/v1/me/flashcard-sets")).json()
    assert [item["id"] for item in mine] == [body["id"]]


async def test_copy_of_an_unknown_or_non_set_share_is_404(api: Api) -> None:
    """SHR-5: slugs that are unknown or point at a chat give 404."""
    api.h.shares.add("chat", "chat", new_id())

    unknown = await api.client.post(
        "/v1/me/flashcard-sets/copy", json={"share_slug": "nope"}
    )
    chat = await api.client.post(
        "/v1/me/flashcard-sets/copy", json={"share_slug": "chat"}
    )

    problem(unknown, 404, "flashcards/share-not-found")
    problem(chat, 404, "flashcards/share-not-found")


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("GET", "/v1/me/flashcard-sets/{set}", None),
        ("PATCH", "/v1/me/flashcard-sets/{set}", {"title": "Mine"}),
        ("DELETE", "/v1/me/flashcard-sets/{set}", None),
        ("PUT", "/v1/me/flashcard-sets/{set}/cards", {"cards": CARDS}),
        ("GET", "/v1/me/flashcard-sets/{set}/study", None),
    ],
)
async def test_another_students_set_is_404_on_every_set_route(
    api: Api, method: str, url: str, body: dict[str, Any] | None
) -> None:
    """Ownership: 404 `flashcards/set-not-found`, and the set is unchanged."""
    created = await api.create()
    api.actor = api.h.other_student

    response = await api.client.request(
        method, url.format(set=created["id"]), json=body
    )

    problem(response, 404, "flashcards/set-not-found")
    assert api.h.store.sets[UUID(created["id"])].title == "Cells"
    assert len(api.h.store.cards_of(UUID(created["id"]))) == 2


async def test_another_students_card_cannot_be_reviewed(api: Api) -> None:
    """Ownership: reviewing a card of someone else is 404 `card-not-found`."""
    created = await api.create()
    api.actor = api.h.other_student

    response = await api.client.post(
        f"/v1/me/flashcards/{created['cards'][0]['id']}/review",
        json={"rating": "easy"},
    )

    problem(response, 404, "flashcards/card-not-found")
    unknown = await api.client.post(
        f"/v1/me/flashcards/{new_id()}/review", json={"rating": "easy"}
    )
    problem(unknown, 404, "flashcards/card-not-found")


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("GET", "/v1/me/flashcard-sets", None),
        ("POST", "/v1/me/flashcard-sets", {"title": "T", "cards": []}),
        ("POST", "/v1/me/flashcard-sets/copy", {"share_slug": "abc"}),
    ],
)
async def test_student_routes_refuse_other_roles(
    api: Api, method: str, url: str, body: dict[str, Any] | None
) -> None:
    """Auth `student`: a teacher gets 403."""
    api.actor = api.h.teacher

    response = await api.client.request(method, url, json=body)

    problem(response, 403, "common/forbidden")
    assert api.h.store.sets == {}


async def test_requests_without_a_token_are_401(
    h: FlashcardsHarness, http_client: Any
) -> None:
    """Auth: no Authorization header → 401."""
    client = await http_client(ROUTERS, None, flashcards=h.services)

    response = await client.get("/v1/me/flashcard-sets")

    problem(response, 401, "auth/unauthorized")


@pytest.mark.parametrize(
    "body",
    [
        {"title": "", "cards": []},
        {"title": "t" * 201, "cards": []},
        {"title": "T", "description": "d" * 1001, "cards": []},
        {"title": "T", "cards": [{"front": "", "back": "a"}]},
        {"title": "T", "cards": [{"front": "a", "back": "b" * 2001}]},
        {"title": "T", "cards": [{"front": "a", "back": "b"}] * 501},
        {"title": "T"},
        {"cards": CARDS},
    ],
)
async def test_create_validates_the_body(api: Api, body: dict[str, Any]) -> None:
    """Plan B10: title 1-200, cards <= 500, front/back 1-2000 characters → 422."""
    response = await api.client.post("/v1/me/flashcard-sets", json=body)

    problem(response, 422, "common/request-validation")
    assert api.h.store.sets == {}


async def test_create_accepts_500_cards(api: Api) -> None:
    """Plan B10: exactly 500 cards are fine."""
    response = await api.client.post(
        "/v1/me/flashcard-sets",
        json={"title": "Big", "cards": [{"front": "a", "back": "b"}] * 500},
    )

    assert response.status_code == 200 and response.json()["card_count"] == 500


@pytest.mark.parametrize(
    "body",
    [
        {"new_per_day": 0},
        {"new_per_day": 201},
        {"reviews_per_day": 0},
        {"reviews_per_day": 2001},
        {"title": ""},
        {"new_per_day": "many"},
    ],
)
async def test_patch_validates_the_limits(api: Api, body: dict[str, Any]) -> None:
    """Plan B10: new_per_day 1-200, reviews_per_day 1-2000 → 422."""
    created = await api.create()

    response = await api.client.patch(
        f"/v1/me/flashcard-sets/{created['id']}", json=body
    )

    problem(response, 422, "common/request-validation")


@pytest.mark.parametrize(
    "cards",
    [
        [{"front": "", "back": "b"}],
        [{"front": "a", "back": "b"}] * 501,
        [{"id": "not-a-uuid", "front": "a", "back": "b"}],
    ],
)
async def test_put_cards_validates_the_list(
    api: Api, cards: list[dict[str, Any]]
) -> None:
    """Plan B10: the same card rules apply to the full list → 422."""
    created = await api.create()

    response = await api.client.put(
        f"/v1/me/flashcard-sets/{created['id']}/cards", json={"cards": cards}
    )

    problem(response, 422, "common/request-validation")
    assert len(api.h.store.cards_of(UUID(created["id"]))) == 2


async def test_put_cards_refuses_the_same_id_twice(api: Api) -> None:
    """WEB-24: a card id may appear once; the domain error is 422 `invalid-cards`."""
    created = await api.create()
    card_id = created["cards"][0]["id"]

    response = await api.client.put(
        f"/v1/me/flashcard-sets/{created['id']}/cards",
        json={
            "cards": [
                {"id": card_id, "front": "a", "back": "b"},
                {"id": card_id, "front": "c", "back": "d"},
            ]
        },
    )

    problem(response, 422, "flashcards/invalid-cards")


@pytest.mark.parametrize("rating", ["", "good", "EASY", 3])
async def test_review_accepts_only_the_four_ratings(api: Api, rating: Any) -> None:
    """Contract: rating is again, hard, medium or easy."""
    created = await api.create()

    response = await api.client.post(
        f"/v1/me/flashcards/{created['cards'][0]['id']}/review",
        json={"rating": rating},
    )

    problem(response, 422, "common/request-validation")


async def test_malformed_ids_are_422(api: Api) -> None:
    """Path ids are UUIDs."""
    response = await api.client.get("/v1/me/flashcard-sets/not-a-uuid")

    problem(response, 422, "common/request-validation")


async def test_a_student_lists_only_their_own_sets(api: Api) -> None:
    """Ownership: lists are per student."""
    await api.create("Mine")
    api.actor = api.h.other_student

    theirs = await api.client.get("/v1/me/flashcard-sets")

    assert theirs.json() == []

"""FlashcardsApiImpl implements the FlashcardsApi contract (§ 3.6) for B7, B9, B15."""

import inspect
from typing import Any
from uuid import UUID

from app.modules.flashcards.application.public_api import FlashcardsApiImpl
from app.modules.flashcards.domain.errors import (
    CardNotFoundError,
    FlashcardSetNotFoundError,
    InvalidCardsError,
)
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.ids import new_id
from app.shared.srs import Rating
from tests.flashcards.conftest import FlashcardsHarness

import pytest


def test_every_contract_method_exists_with_the_same_parameters() -> None:
    """§ 3.6: names, parameter names, kinds and defaults equal the Protocol."""
    contract = {
        name: inspect.signature(member)
        for name, member in inspect.getmembers(FlashcardsApi, inspect.isfunction)
        if not name.startswith("_")
    }

    assert set(contract) == {
        "list_sets",
        "get_set",
        "create_set",
        "add_cards",
        "update_card",
        "set_owner",
    }
    for name, expected in contract.items():
        actual = inspect.signature(getattr(FlashcardsApiImpl, name))
        assert [(p.name, p.kind, p.default) for p in actual.parameters.values()] == [
            (p.name, p.kind, p.default) for p in expected.parameters.values()
        ], name
        assert inspect.iscoroutinefunction(getattr(FlashcardsApiImpl, name)), name


async def test_list_sets_gives_counts_for_today(h: FlashcardsHarness) -> None:
    """MCP-8 list_flashcard_sets: card counts and today's due/new cards."""
    mine = await h.make_set(3, title="Mine")
    await h.make_set(2, title="Not mine", owner=h.other_student)
    await h.rate(mine.cards[0].id, Rating.MEDIUM)

    listed = await h.services.public.list_sets(h.student.user_id)

    assert listed == [
        {
            "id": mine.id,
            "title": "Mine",
            "description": None,
            "source": "manual",
            "card_count": 3,
            "due_today": 1,
            "new_today": 2,
        }
    ]


async def test_get_set_for_the_owner_has_title_and_cards(h: FlashcardsHarness) -> None:
    """B9/B15: `title` and `cards[{id, front, back}]` (plus position)."""
    created = await h.make_set(2, title="Cells")

    found = await h.services.public.get_set(created.id, h.student.user_id)

    assert found is not None
    assert found["id"] == created.id and found["title"] == "Cells"
    assert found["owner_id"] == h.student.user_id
    assert found["card_count"] == 2 and found["description"] is None
    assert found["cards"] == [
        {"id": c.id, "position": i, "front": f"front {i}", "back": f"back {i}"}
        for i, c in enumerate(created.cards)
    ]


async def test_get_set_without_an_owner_is_the_public_read_for_shares(
    h: FlashcardsHarness,
) -> None:
    """B7 SHR-5: any set can be read, and no study progress leaks."""
    created = await h.make_set(1)
    await h.rate(created.cards[0].id, Rating.EASY)

    shared = await h.services.public.get_set(created.id, None)

    assert shared is not None and shared["owner_id"] == h.student.user_id
    assert set(shared["cards"][0]) == {"id", "position", "front", "back"}
    assert "state" not in str(shared) and "due_at" not in str(shared)


async def test_get_set_hides_other_owners_sets_and_unknown_ids(
    h: FlashcardsHarness,
) -> None:
    """B9/B15 ownership: a set of someone else reads as missing."""
    created = await h.make_set(1)

    assert await h.services.public.get_set(created.id, h.other_student.user_id) is None
    assert await h.services.public.get_set(new_id(), h.student.user_id) is None
    assert await h.services.public.get_set(new_id(), None) is None


async def test_create_set_saves_the_source_and_the_chat(h: FlashcardsHarness) -> None:
    """B9 AI-2: sets made by the assistant remember the chat (source `ai`)."""
    chat_id = new_id()

    created = await h.services.public.create_set(
        h.student.user_id,
        "From chat",
        [("Q1", "A1"), ("Q2", "A2")],
        source="ai",
        source_chat_id=chat_id,
        description="Made by the assistant",
    )

    assert isinstance(created["id"], UUID)
    assert (created["title"], created["card_count"]) == ("From chat", 2)
    assert created["source"] == "ai"
    assert created["description"] == "Made by the assistant"
    assert [(c["front"], c["back"]) for c in created["cards"]] == [
        ("Q1", "A1"),
        ("Q2", "A2"),
    ]
    stored = h.store.sets[created["id"]]
    assert (stored.owner_id, stored.source_chat_id) == (h.student.user_id, chat_id)
    assert all(c.state.value == "new" for c in h.store.cards_of(created["id"]))


async def test_create_set_from_mcp_is_marked(h: FlashcardsHarness) -> None:
    """B15 MCP-8: sets made through MCP have source `mcp`."""
    created = await h.services.public.create_set(
        h.student.user_id, "Via MCP", [("a", "b")], source="mcp"
    )

    assert created["source"] == "mcp"


async def test_create_set_checks_the_limits(h: FlashcardsHarness) -> None:
    """Plan B10: the same rules as the HTTP endpoint."""
    with pytest.raises(InvalidCardsError):
        await h.services.public.create_set(
            h.student.user_id,
            "Too big",
            [("a", "b")] * 501,
            source="manual",
        )

    assert h.store.sets == {}


async def test_add_cards_returns_the_set_with_the_new_size(
    h: FlashcardsHarness,
) -> None:
    """B9 add_flashcards reads `card_count`; B15 returns the set."""
    created = await h.make_set(1)

    updated = await h.services.public.add_cards(
        h.student.user_id, created.id, [("more", "cards"), ("and", "more")]
    )

    assert updated["card_count"] == 3 and updated["id"] == created.id
    assert [c["front"] for c in updated["cards"]] == ["front 0", "more", "and"]


async def test_add_cards_to_another_students_set_is_refused(
    h: FlashcardsHarness,
) -> None:
    """Ownership: the set looks missing and nothing is added."""
    created = await h.make_set(1)

    with pytest.raises(FlashcardSetNotFoundError):
        await h.services.public.add_cards(
            h.other_student.user_id, created.id, [("a", "b")]
        )

    assert len(h.store.cards_of(created.id)) == 1


async def test_update_card_returns_the_card(h: FlashcardsHarness) -> None:
    """B15 update_flashcard: front, back or both."""
    created = await h.make_set(2)
    card = created.cards[1]

    updated = await h.services.public.update_card(
        h.student.user_id, card.id, "Better question", None
    )

    assert updated == {
        "id": card.id,
        "set_id": created.id,
        "position": 1,
        "front": "Better question",
        "back": "back 1",
    }


async def test_update_card_of_another_students_set_is_refused(
    h: FlashcardsHarness,
) -> None:
    """B15: "cards in sets owned by someone else are refused"."""
    created = await h.make_set(1)

    with pytest.raises(CardNotFoundError):
        await h.services.public.update_card(
            h.other_student.user_id, created.cards[0].id, "x", "y"
        )

    assert h.store.cards[created.cards[0].id].front == "front 0"


async def test_set_owner_answers_for_links_and_mcp(h: FlashcardsHarness) -> None:
    """B7 create_share and B15 add_flashcards check the owner first."""
    created = await h.make_set(1)

    assert await h.services.public.set_owner(created.id) == h.student.user_id
    assert await h.services.public.set_owner(new_id()) is None


async def test_results_survive_json_conversion(h: FlashcardsHarness) -> None:
    """B9 and B15 turn results into JSON; ids become strings."""
    from app.interfaces.mcp.jsonable import to_jsonable

    created = await h.services.public.create_set(
        h.student.user_id, "J", [("a", "b")], source="mcp"
    )
    results: list[Any] = [
        created,
        await h.services.public.list_sets(h.student.user_id),
        await h.services.public.get_set(created["id"], h.student.user_id),
        await h.services.public.add_cards(
            h.student.user_id, created["id"], [("c", "d")]
        ),
        await h.services.public.update_card(
            h.student.user_id, created["cards"][0]["id"], "e", None
        ),
    ]

    converted = to_jsonable(results)

    assert converted[0]["id"] == str(created["id"])
    assert converted[0]["cards"][0]["id"] == str(created["cards"][0]["id"])
    assert converted[1][0]["due_today"] == 0

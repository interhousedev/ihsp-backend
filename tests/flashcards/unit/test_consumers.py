"""The users of FlashcardsApi (AI tools, share pages) work against the real module."""

from uuid import UUID

from app.modules.ai.application.tools.add_flashcards import AddFlashcards
from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.create_flashcard_set import CreateFlashcardSet
from app.modules.ai.application.tools.get_flashcard_set import GetFlashcardSet
from app.modules.ai.application.tools.list_flashcard_sets import ListFlashcardSets
from app.modules.ai.domain.errors import ToolFailedError
from app.shared.ids import new_id
from tests.flashcards.conftest import FlashcardsHarness

import pytest


def context(h: FlashcardsHarness, chat_id: UUID) -> ToolContext:
    """The student's tool context in a chat."""
    return ToolContext(actor=h.student, chat_id=chat_id, locale="en")


async def test_the_ai_tools_create_list_read_and_extend_a_set(
    h: FlashcardsHarness,
) -> None:
    """AI-5: create, list, read and extend a set with the assistant's tools."""
    chat_id = new_id()
    ctx = context(h, chat_id)
    api = h.services.public
    create, listing = CreateFlashcardSet(api), ListFlashcardSets(api)
    read, add = GetFlashcardSet(api), AddFlashcards(api)

    made = await create.run(
        create.parse(
            {
                "title": "Cells",
                "description": "Chapter 1",
                "cards": [{"front": "Q1", "back": "A1"}],
            }
        ),
        ctx,
    )
    set_id = UUID(made["set_id"])
    listed = await listing.run(listing.parse({}), ctx)
    opened = await read.run(read.parse({"set_id": str(set_id)}), ctx)
    added = await add.run(
        add.parse({"set_id": str(set_id), "cards": [{"front": "Q2", "back": "A2"}]}),
        ctx,
    )

    assert made == {"set_id": str(set_id), "title": "Cells", "card_count": 1}
    stored = h.store.sets[set_id]
    assert (stored.source.value, stored.source_chat_id) == ("ai", chat_id)
    assert [row["id"] for row in listed["items"]] == [set_id]
    assert opened["title"] == "Cells"
    assert [c["front"] for c in opened["cards"]] == ["Q1"]
    assert added == {"set_id": str(set_id), "added": 1, "card_count": 2}


async def test_the_ai_tools_cannot_read_or_extend_another_students_set(
    h: FlashcardsHarness,
) -> None:
    """AI-5: a set of someone else is "not found" for the tool."""
    theirs = await h.make_set(1, owner=h.other_student)
    ctx = context(h, new_id())
    api = h.services.public
    read, add = GetFlashcardSet(api), AddFlashcards(api)

    with pytest.raises(ToolFailedError):
        await read.run(read.parse({"set_id": str(theirs.id)}), ctx)
    with pytest.raises(ToolFailedError):
        await add.validate(
            add.parse(
                {"set_id": str(theirs.id), "cards": [{"front": "a", "back": "b"}]}
            ),
            ctx,
        )

    assert len(h.store.cards_of(theirs.id)) == 1


async def test_a_share_page_can_render_what_get_set_returns(
    h: FlashcardsHarness,
) -> None:
    """SHR-5: B7 reads `title` and `cards[{id, front, back}]` with owner_id=None."""
    created = await h.make_set(2, title="Shared")

    data = await h.services.public.get_set(created.id, None)

    assert data is not None
    assert data["title"] == "Shared"
    cards = [
        (str(card["id"]), str(card["front"]), str(card["back"]))
        for card in data.get("cards", [])
    ]
    assert cards == [(str(c.id), c.front, c.back) for c in created.cards]


async def test_creating_a_share_checks_the_owner_with_set_owner(
    h: FlashcardsHarness,
) -> None:
    """SHR-1: B7 allows a share only when `set_owner` is the actor."""
    created = await h.make_set(1)

    owner = await h.services.public.set_owner(created.id)

    assert owner == h.student.user_id and owner != h.other_student.user_id

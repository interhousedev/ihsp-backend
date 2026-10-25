"""SHR-5: copying a shared set gives the student their own set with fresh progress."""

from app.modules.flashcards.domain.errors import ShareNotFoundError
from app.shared.ids import new_id
from app.shared.srs import CardState, Rating
from tests.flashcards.conftest import FlashcardsHarness

import pytest


async def test_a_copy_has_the_same_text_and_fresh_progress(
    h: FlashcardsHarness,
) -> None:
    """SHR-5: new cards, source `copied`, `copied_from_set_id` = the original."""
    original = await h.make_set(3, title="Shared set")
    await h.services.update_set.execute(
        owner_id=h.student.user_id,
        set_id=original.id,
        description="From Aziza",
        new_per_day=5,
    )
    await h.rate(original.cards[0].id, Rating.EASY)
    h.shares.add("abc123", "flashcard_set", original.id)

    copy = await h.services.copy_from_share.execute(
        actor=h.other_student, share_slug="abc123"
    )

    assert copy.id != original.id
    assert (copy.title, copy.description, copy.source) == (
        "Shared set",
        "From Aziza",
        "copied",
    )
    assert [c.front for c in copy.cards] == ["front 0", "front 1", "front 2"]
    assert [c.position for c in copy.cards] == [0, 1, 2]
    assert {c.state for c in copy.cards} == {"new"}
    assert {c.due_at for c in copy.cards} == {None}
    assert not {c.id for c in copy.cards} & {c.id for c in original.cards}
    assert copy.card_count == 3 and (copy.due_today, copy.new_today) == (0, 3)
    assert (copy.new_per_day, copy.reviews_per_day) == (20, 200)
    stored = h.store.sets[copy.id]
    assert stored.owner_id == h.other_student.user_id
    assert stored.copied_from_set_id == original.id and stored.source_chat_id is None


async def test_the_original_is_not_changed_by_a_copy(h: FlashcardsHarness) -> None:
    """SHR-5: the owner keeps their set and progress."""
    original = await h.make_set(2)
    await h.rate(original.cards[0].id, Rating.EASY)
    h.shares.add("slug", "flashcard_set", original.id)

    await h.services.copy_from_share.execute(actor=h.other_student, share_slug="slug")

    assert len(h.store.sets) == 2 and len(h.store.cards) == 4
    assert h.store.cards[original.cards[0].id].state is CardState.REVIEW
    mine = await h.services.list_sets.execute(owner_id=h.student.user_id)
    assert [s.id for s in mine] == [original.id]


async def test_a_student_can_copy_their_own_shared_set(h: FlashcardsHarness) -> None:
    """SHR-5: copying is allowed for the owner too (a fresh start)."""
    original = await h.make_set(1)
    h.shares.add("own", "flashcard_set", original.id)

    copy = await h.services.copy_from_share.execute(actor=h.student, share_slug="own")

    assert copy.id != original.id and copy.source == "copied"


@pytest.mark.parametrize("slug", ["missing", "chat-share"])
async def test_only_active_flashcard_shares_can_be_copied(
    h: FlashcardsHarness, slug: str
) -> None:
    """SHR-5: unknown or revoked slugs and chat shares give 404."""
    h.shares.add("chat-share", "chat", new_id())

    with pytest.raises(ShareNotFoundError) as raised:
        await h.services.copy_from_share.execute(actor=h.student, share_slug=slug)

    assert raised.value.status == 404
    assert raised.value.code == "flashcards/share-not-found"
    assert h.store.sets == {}


async def test_a_share_of_a_deleted_set_cannot_be_copied(h: FlashcardsHarness) -> None:
    """SHR-5: the set is gone, so is the copy source."""
    original = await h.make_set(1)
    h.shares.add("gone", "flashcard_set", original.id)
    await h.services.delete_set.execute(owner_id=h.student.user_id, set_id=original.id)

    with pytest.raises(ShareNotFoundError):
        await h.services.copy_from_share.execute(
            actor=h.other_student, share_slug="gone"
        )

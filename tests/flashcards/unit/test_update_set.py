"""WEB-23, WEB-24: title, description and the two daily limits."""

from app.modules.flashcards.application.update_set import UNSET
from app.modules.flashcards.domain.errors import (
    FlashcardSetNotFoundError,
    InvalidSetError,
)
from tests.flashcards.conftest import FlashcardsHarness

import pytest


async def test_every_field_can_be_changed(h: FlashcardsHarness) -> None:
    """WEB-23: new_per_day 1-200 and reviews_per_day 1-2000 are editable."""
    created = await h.make_set(2)

    updated = await h.services.update_set.execute(
        owner_id=h.student.user_id,
        set_id=created.id,
        title=" Mitosis ",
        description="Phases",
        new_per_day=5,
        reviews_per_day=50,
    )

    assert (updated.title, updated.description) == ("Mitosis", "Phases")
    assert (updated.new_per_day, updated.reviews_per_day) == (5, 50)
    assert len(updated.cards) == 2
    stored = h.store.sets[created.id]
    assert (stored.new_per_day, stored.reviews_per_day) == (5, 50)


async def test_fields_that_are_not_sent_stay_as_they_are(
    h: FlashcardsHarness,
) -> None:
    """PATCH: only the sent fields change."""
    created = await h.make_set(1, title="Keep me")
    await h.services.update_set.execute(
        owner_id=h.student.user_id, set_id=created.id, description="Keep too"
    )

    updated = await h.services.update_set.execute(
        owner_id=h.student.user_id, set_id=created.id, new_per_day=7
    )

    assert (updated.title, updated.description) == ("Keep me", "Keep too")
    assert (updated.new_per_day, updated.reviews_per_day) == (7, 200)


async def test_a_null_description_clears_it(h: FlashcardsHarness) -> None:
    """PATCH: `description: null` removes the description."""
    created = await h.make_set(1)
    await h.services.update_set.execute(
        owner_id=h.student.user_id, set_id=created.id, description="Text"
    )

    cleared = await h.services.update_set.execute(
        owner_id=h.student.user_id, set_id=created.id, description=None
    )
    untouched = await h.services.update_set.execute(
        owner_id=h.student.user_id, set_id=created.id, description=UNSET
    )

    assert cleared.description is None and untouched.description is None


@pytest.mark.parametrize(
    ("title", "new_per_day", "reviews_per_day"),
    [
        (None, 0, None),
        (None, 201, None),
        (None, None, 0),
        (None, None, 2001),
        ("  ", None, None),
        ("t" * 201, None, None),
    ],
)
async def test_values_out_of_range_are_refused_not_clamped(
    h: FlashcardsHarness,
    title: str | None,
    new_per_day: int | None,
    reviews_per_day: int | None,
) -> None:
    """WEB-23: the set keeps its old values after a refused change."""
    created = await h.make_set(1)

    with pytest.raises(InvalidSetError):
        await h.services.update_set.execute(
            owner_id=h.student.user_id,
            set_id=created.id,
            title=title,
            new_per_day=new_per_day,
            reviews_per_day=reviews_per_day,
        )

    stored = h.store.sets[created.id]
    assert (stored.title, stored.new_per_day, stored.reviews_per_day) == (
        "Cells",
        20,
        200,
    )


async def test_a_description_over_1000_characters_is_refused(
    h: FlashcardsHarness,
) -> None:
    """WEB-22: descriptions have at most 1000 characters."""
    created = await h.make_set(1)

    with pytest.raises(InvalidSetError):
        await h.services.update_set.execute(
            owner_id=h.student.user_id, set_id=created.id, description="d" * 1001
        )


@pytest.mark.parametrize(("new_per_day", "reviews_per_day"), [(1, 1), (200, 2000)])
async def test_the_edges_of_the_ranges_are_accepted(
    h: FlashcardsHarness, new_per_day: int, reviews_per_day: int
) -> None:
    """WEB-23: 1 to 200 new cards and 1 to 2000 reviews per day."""
    created = await h.make_set(1)

    updated = await h.services.update_set.execute(
        owner_id=h.student.user_id,
        set_id=created.id,
        new_per_day=new_per_day,
        reviews_per_day=reviews_per_day,
    )

    assert (updated.new_per_day, updated.reviews_per_day) == (
        new_per_day,
        reviews_per_day,
    )


async def test_another_students_set_cannot_be_changed(h: FlashcardsHarness) -> None:
    """Ownership: 404 and nothing changes."""
    created = await h.make_set(1)

    with pytest.raises(FlashcardSetNotFoundError):
        await h.services.update_set.execute(
            owner_id=h.other_student.user_id, set_id=created.id, title="Mine now"
        )

    assert h.store.sets[created.id].title == "Cells"

"""LIB-7: a shelf entry moves between want, reading and done."""

import datetime as dt

from app.modules.library.domain.enums import ShelfState
from app.modules.library.domain.reader_shelf import place_on_shelf
from app.shared.ids import new_id

USER = new_id()
ITEM = new_id()
NOW = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)
LATER = NOW + dt.timedelta(days=2)


def test_new_entry_in_done_has_a_finish_date() -> None:
    """LIB-7: finishing sets `finished_at`."""
    entry = place_on_shelf(
        None, user_id=USER, item_id=ITEM, state=ShelfState.DONE, now=NOW
    )

    assert entry.finished_at == NOW
    assert entry.created_at == entry.updated_at == NOW


def test_new_entry_in_want_has_no_finish_date() -> None:
    """LIB-7: only done entries carry a finish date."""
    entry = place_on_shelf(
        None, user_id=USER, item_id=ITEM, state=ShelfState.WANT, now=NOW
    )

    assert entry.finished_at is None


def test_moving_to_done_sets_the_finish_date_and_back_clears_it() -> None:
    """LIB-7: reading -> done -> reading."""
    reading = place_on_shelf(
        None, user_id=USER, item_id=ITEM, state=ShelfState.READING, now=NOW
    )

    done = place_on_shelf(
        reading, user_id=USER, item_id=ITEM, state=ShelfState.DONE, now=LATER
    )
    again = place_on_shelf(
        done, user_id=USER, item_id=ITEM, state=ShelfState.READING, now=LATER
    )

    assert done.finished_at == LATER
    assert again.finished_at is None
    assert again.created_at == NOW


def test_putting_the_same_state_changes_nothing() -> None:
    """LIB-7: a repeated PUT keeps the finish date and the timestamp."""
    done = place_on_shelf(
        None, user_id=USER, item_id=ITEM, state=ShelfState.DONE, now=NOW
    )

    same = place_on_shelf(
        done, user_id=USER, item_id=ITEM, state=ShelfState.DONE, now=LATER
    )

    assert same.finished_at == NOW
    assert same.updated_at == NOW

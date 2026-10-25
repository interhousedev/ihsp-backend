"""Items without refs are honest general knowledge; invented labels are not."""

from app.modules.notebooks.domain.artifacts.refs import (
    cites_honestly,
    keep_items_with_refs,
)


def test_empty_refs_are_honest_and_invalid_labels_are_not() -> None:
    """The system prompt asks for empty refs on own-knowledge items."""
    assert cites_honestly([], [])
    assert cites_honestly(None, [])
    assert cites_honestly(["", "  "], [])
    assert cites_honestly(["S1:P1"], ["S1:P1"])
    assert cites_honestly(["S9:P9", "S1:P1"], ["S1:P1"])
    assert not cites_honestly(["S9:P9"], [])


def test_keep_items_drops_only_the_untrusted_half_rule() -> None:
    """Untrusted items go when at least half of the request stays."""
    items = [("a", True), ("b", True), ("c", False)]

    assert keep_items_with_refs(items, lambda i: i[1], 4) == items[:2]
    assert keep_items_with_refs(items, lambda i: i[1], 5) == items

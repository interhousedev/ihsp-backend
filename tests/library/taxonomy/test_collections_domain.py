"""LIB-4: collections are librarian-curated shelves with a limited size and names."""

from app.modules.library.domain.taxonomy_collections import (
    COLLECTION_MAX_ITEMS,
    check_item_count,
    clean_description,
    clean_title,
)
from app.modules.library.domain.taxonomy_errors import (
    CollectionTooLongError,
    NameRequiredError,
)

import pytest


def test_title_needs_at_least_one_language() -> None:
    """LIB-4: a collection without any title is refused."""
    assert clean_title({"uz": " Klassika ", "ru": "", "en": "Classics"}) == {
        "uz": "Klassika",
        "ru": "",
        "en": "Classics",
    }
    with pytest.raises(NameRequiredError):
        clean_title({"uz": "", "ru": " ", "en": ""})


def test_blank_description_is_stored_as_none() -> None:
    """LIB-4: ManageCollection.description is null when nothing was written."""
    assert clean_description(None) == {}
    assert clean_description({"uz": " ", "ru": "", "en": ""}) == {}
    assert clean_description({"uz": "", "ru": "Лето", "en": ""}) == {
        "uz": "",
        "ru": "Лето",
        "en": "",
    }


def test_a_collection_holds_a_limited_number_of_items() -> None:
    """LIB-4: very long shelves are refused."""
    check_item_count(COLLECTION_MAX_ITEMS)

    with pytest.raises(CollectionTooLongError):
        check_item_count(COLLECTION_MAX_ITEMS + 1)

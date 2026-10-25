"""LIB-5, LIB-12: our search becomes the query UniLibrary understands."""

from app.modules.library.domain.enums import ExternalAccess
from app.modules.library.infrastructure.unilibrary.params import (
    list_cache_key,
    list_query,
)
from app.modules.library.ports.external_catalog import ExternalSearch


def test_plain_search_sends_paging_language_category_and_newest_first() -> None:
    """LIB-5: only what is set is sent."""
    query = list_query(ExternalSearch())

    assert query == {
        "page": 1,
        "limit": 20,
        "language": "uz",
        "sort": "desc",
        "sort_direction": "id",
        "resource_category_id": 1,
    }


def test_every_filter_has_its_parameter() -> None:
    """LIB-5: q, field, type, language and access map to their names."""
    search = ExternalSearch(
        q="  elektron   sxemalar ",
        page=3,
        limit=50,
        language="ru",
        category=1,
        field_id=27,
        type_id=9,
        language_id=26,  # "Lotin"
        access=ExternalAccess.PARTIAL,
    )

    query = list_query(search)

    assert query["name"] == "elektron sxemalar"
    assert query["page"] == 3
    assert query["limit"] == 50
    assert query["language"] == "ru"
    assert query["resource_field_id"] == 27
    assert query["resource_type_id"] == 9
    assert query["resource_language_id"] == 26
    assert query["resource_modifier_id"] == 2


def test_access_classes_become_modifier_ids() -> None:
    """LIB-12: open, partial, closed are 1, 2, 3."""
    ids = {
        access: list_query(ExternalSearch(access=access))["resource_modifier_id"]
        for access in ExternalAccess
    }

    assert ids == {
        ExternalAccess.OPEN: 1,
        ExternalAccess.PARTIAL: 2,
        ExternalAccess.CLOSED: 3,
    }


def test_blank_text_is_not_sent() -> None:
    """LIB-5: an empty box is a browse, not a title search."""
    assert "name" not in list_query(ExternalSearch(q="   "))


def test_paging_is_kept_in_range_and_unknown_language_becomes_uzbek() -> None:
    """LIB-12: UniLibrary accepts at most 100 per page; names are uz, ru or en."""
    query = list_query(ExternalSearch(page=0, limit=500, language="de"))

    assert (query["page"], query["limit"], query["language"]) == (1, 100, "uz")


def test_same_search_has_the_same_cache_key() -> None:
    """LIB-12: the key is a hash of the normalised parameters."""
    first = list_cache_key(list_query(ExternalSearch(q="fizika  10", field_id=27)))
    second = list_cache_key(list_query(ExternalSearch(field_id=27, q="fizika 10")))

    assert first == second
    assert first.startswith("library:ext:list:")
    assert len(first) == len("library:ext:list:") + 40


def test_other_page_or_filter_has_another_cache_key() -> None:
    """LIB-12: different questions never share an answer."""
    base = list_cache_key(list_query(ExternalSearch(q="fizika")))

    assert base != list_cache_key(list_query(ExternalSearch(q="fizika", page=2)))
    assert base != list_cache_key(list_query(ExternalSearch(q="fizika", field_id=1)))
    assert base != list_cache_key(list_query(ExternalSearch(q="fizika", language="ru")))

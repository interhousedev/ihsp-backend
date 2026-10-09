"""LIB-12: how UniLibrary ids and texts turn into lyceum values (pure rules)."""

from app.modules.library.domain.enums import ExternalAccess, ItemLanguage, ItemType
from app.modules.library.domain.external_mapping import (
    access_for,
    cut_description,
    item_type_for,
    language_for,
    language_id_for_code,
    view_url,
)

import pytest


@pytest.mark.parametrize(
    ("category", "path"),
    [(1, "literature"), (2, "monograph"), (3, "dissertation"), (4, "articles")],
)
def test_view_url_follows_the_category(category: int, path: str) -> None:
    """LIB-12: the public page of a record depends on its category."""
    assert view_url(category, "896986") == f"https://unilibrary.uz/{path}/896986"


def test_view_url_refuses_an_unknown_category() -> None:
    """LIB-12: a category we cannot link to is an error, not a guessed path."""
    with pytest.raises(ValueError, match="category"):
        view_url(9, "1")


@pytest.mark.parametrize(
    ("modifier_id", "access"),
    [
        (1, ExternalAccess.OPEN),
        (2, ExternalAccess.PARTIAL),
        (3, ExternalAccess.CLOSED),
        (None, ExternalAccess.CLOSED),
        (99, ExternalAccess.CLOSED),
    ],
)
def test_access_class_comes_from_the_modifier(
    modifier_id: int | None, access: ExternalAccess
) -> None:
    """LIB-12: 1, 2, 3 are open, partial, closed; anything else is closed."""
    assert access_for(modifier_id) is access


@pytest.mark.parametrize(
    ("language_id", "language"),
    [
        (2, ItemLanguage.UZ_LATN),
        (26, ItemLanguage.UZ_LATN),  # "Lotin" is Uzbek in Latin script
        (3, ItemLanguage.RU),
        (7, ItemLanguage.EN),
        (6, ItemLanguage.QQ),
        (13, ItemLanguage.OTHER),
        (None, ItemLanguage.OTHER),
    ],
)
def test_language_ids_map_to_item_languages(
    language_id: int | None, language: ItemLanguage
) -> None:
    """LIB-12: ids 2 and 26 are Latin Uzbek; unknown languages are `other`."""
    assert language_for(language_id) is language


@pytest.mark.parametrize(
    ("type_id", "item_type"),
    [
        (9, ItemType.TEXTBOOK),
        (2, ItemType.MANUAL),
        (3, ItemType.MANUAL),
        (11, ItemType.MANUAL),
        (19, ItemType.FICTION),
        (20, ItemType.DICTIONARY),
        (21, ItemType.REFERENCE),
        (22, ItemType.OTHER),
        (25, ItemType.OTHER),
        (26, ItemType.OTHER),
        (None, ItemType.OTHER),
    ],
)
def test_literature_types_map_to_the_lyceum_list(
    type_id: int | None, item_type: ItemType
) -> None:
    """LIB-12: doc 3.2, the UniLibrary types of category 1 onto our list."""
    assert item_type_for(1, type_id) is item_type


def test_articles_are_articles_and_other_categories_are_other() -> None:
    """LIB-12: type ids are verified for literature only."""
    assert item_type_for(4, 9) is ItemType.ARTICLE
    assert item_type_for(2, 9) is ItemType.OTHER
    assert item_type_for(3, None) is ItemType.OTHER


@pytest.mark.parametrize(
    ("code", "language_id"),
    [("uz_latn", 2), ("ru", 3), ("en", 7), ("qq", 6), ("26", 26), ("3", 3)],
)
def test_language_filter_accepts_codes_and_ids(code: str, language_id: int) -> None:
    """LIB-5: the search filter may be our language code or a UniLibrary id."""
    assert language_id_for_code(code) == language_id


def test_language_filter_without_a_known_code_is_not_sent() -> None:
    """LIB-5: `uz_cyrl` has no UniLibrary id, so the filter is dropped."""
    assert language_id_for_code("uz_cyrl") is None
    assert language_id_for_code("") is None


def test_short_description_is_unchanged_and_tidy() -> None:
    """LIB-12: whitespace is collapsed and tags are stripped."""
    text = "  Elektron   sxemalar <b>asoslari</b>\n bilan &amp; tanishuv. "

    assert cut_description(text, 600) == "Elektron sxemalar asoslari bilan & tanishuv."


def test_long_description_is_cut_at_the_limit_with_an_ellipsis() -> None:
    """LIB-12 / doc 3.3: `abstract_name` is cut at 600 characters."""
    text = "so'z " * 400

    cut = cut_description(text, 600)

    assert cut is not None
    assert len(cut) == 600
    assert cut.endswith("…")


def test_empty_description_is_none() -> None:
    """LIB-12: nothing to show."""
    assert cut_description(None, 600) is None
    assert cut_description("   ", 600) is None

"""LIB-7: search queries meet Uzbek Latin and Cyrillic, and Russian stays Russian."""

from app.modules.library.domain.enums import ItemLanguage
from app.modules.library.domain.search_query import (
    MAX_QUERY_TOKENS,
    build_search_text,
    item_search_language,
    parse_query,
)

import pytest


def test_blank_or_symbol_only_query_is_no_query() -> None:
    """LIB-7: nothing to search for gives None."""
    assert parse_query("") is None
    assert parse_query("   ") is None
    assert parse_query("!!! ??") is None


def test_latin_query_keeps_its_words_and_prefixes_the_last_one() -> None:
    """LIB-7: the last word matches as a prefix (search as you type)."""
    parsed = parse_query("Fizika 10")

    assert parsed is not None
    assert parsed.raw == "fizika 10"
    assert parsed.tsquery == "('fizika' & '10':*)"


def test_cyrillic_uzbek_query_gets_a_latin_form() -> None:
    """LIB-7: "ўзбек" finds "oʻzbek" and "o'zbek"."""
    parsed = parse_query("ўзбек")

    assert parsed is not None
    assert parsed.forms == ("ўзбек", "oʻzbek")
    assert "'oʻzbek':*" in parsed.tsquery
    assert "'ўзбек':*" in parsed.tsquery


def test_apostrophe_variants_meet_one_form() -> None:
    """LIB-7: o', oʻ, o‘ and oʼ are the same query."""
    forms = {
        parse_query(variant).forms[-1]  # type: ignore[union-attr]
        for variant in ("o'zbek", "oʻzbek", "o‘zbek", "o’zbek")
    }

    assert forms == {"oʻzbek"}


def test_russian_query_keeps_the_raw_form_for_russian_items() -> None:
    """LIB-7: Russian items are stored untransliterated, so the raw form stays."""
    parsed = parse_query("Физика")

    assert parsed is not None
    assert parsed.forms[0] == "физика"
    assert "'физика':*" in parsed.tsquery


def test_query_is_cut_to_the_token_limit() -> None:
    """LIB-7: absurdly long queries do not build absurd tsqueries."""
    parsed = parse_query(" ".join(f"w{n}" for n in range(50)))

    assert parsed is not None
    assert parsed.tsquery.count("&") == MAX_QUERY_TOKENS - 1


def test_quotes_and_operators_cannot_break_the_tsquery() -> None:
    """LIB-7: user input never reaches to_tsquery as syntax."""
    parsed = parse_query("a' & (b) | !c <-> d:*")

    assert parsed is not None
    assert "(" not in parsed.tsquery.replace("('", "").replace(")", "")
    assert "!" not in parsed.tsquery
    assert "<->" not in parsed.tsquery


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        (ItemLanguage.UZ_LATN, "uz"),
        (ItemLanguage.UZ_CYRL, "uz"),
        (ItemLanguage.QQ, "uz"),
        (ItemLanguage.RU, "ru"),
        (ItemLanguage.EN, "en"),
        (ItemLanguage.OTHER, "other"),
    ],
)
def test_language_picks_the_normalisation(
    language: ItemLanguage, expected: str
) -> None:
    """LIB-7: only Uzbek items are transliterated."""
    assert item_search_language(language) == expected


def test_search_text_of_a_cyrillic_uzbek_book_is_latin() -> None:
    """LIB-7: title, subtitle, authors and description in one Latin string."""
    text = build_search_text(
        language=ItemLanguage.UZ_CYRL,
        title="Ўзбек адабиёти",
        subtitle="Дарслик",
        authors=["Абдулла Қодирий"],
        description="Ғазал ва шеър",
    )

    assert text == (
        "o\u02bbzbek adabiyoti darslik abdulla qodiriy g\u02bbazal va she\u02bcr"
    )


def test_search_text_of_a_russian_book_is_only_lowercased() -> None:
    """LIB-7: Russian items are not transliterated."""
    text = build_search_text(
        language=ItemLanguage.RU,
        title="Физика 10",
        subtitle=None,
        authors=["И. Иванов"],
        description=None,
    )

    assert text == "физика 10 и. иванов"

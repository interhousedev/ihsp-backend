"""LIB-7: Қ, Ғ, Ў and Ҳ are found by К, Г, У and Х, and the other way round."""

import re

from app.modules.library.domain.enums import ItemLanguage
from app.modules.library.domain.search_query import (
    build_search_text,
    parse_query,
    spellings,
)

import pytest

_TERM = re.compile(r"'([^']+)'")


def _terms(match: str) -> set[str]:
    """The quoted words of a tsquery, without their prefix marks."""
    return set(_TERM.findall(match))


def _stored(language: ItemLanguage, title: str) -> str:
    """The word a title is stored as in `search_text` (one word, so one term)."""
    return build_search_text(
        language=language, title=title, subtitle=None, authors=[], description=None
    )


@pytest.mark.parametrize(
    ("language", "stored_title"),
    [
        (ItemLanguage.UZ_CYRL, "Қодирий"),
        (ItemLanguage.UZ_LATN, "Qodiriy"),
        (ItemLanguage.UZ_LATN, "Kodiriy"),
    ],
)
@pytest.mark.parametrize("typed", ["Кодирий", "Қодирий", "Qodiriy", "Kodiriy"])
def test_every_spelling_of_a_stored_name_is_found(
    language: ItemLanguage, stored_title: str, typed: str
) -> None:
    """LIB-7: the query side covers the stored side; any spelling finds any other."""
    stored = _stored(language, stored_title)
    parsed = parse_query(typed)

    assert parsed is not None
    assert stored in _terms(parsed.match)


@pytest.mark.parametrize(
    ("language", "stored_title", "typed"),
    [
        (ItemLanguage.UZ_CYRL, "Ғулистон", "Гулистон"),
        (ItemLanguage.UZ_LATN, "Gʻuliston", "Гулистон"),
        (ItemLanguage.UZ_CYRL, "Ўзбек", "Узбек"),
        (ItemLanguage.UZ_LATN, "Oʻzbek", "Узбек"),
        (ItemLanguage.UZ_CYRL, "Ҳасан", "Хасан"),
        (ItemLanguage.UZ_LATN, "Xasan", "Ҳасан"),
    ],
)
def test_other_folded_letters_are_found_both_ways(
    language: ItemLanguage, stored_title: str, typed: str
) -> None:
    """LIB-7: Ғ/Г, Ў/У and Ҳ/Х fold on both sides too."""
    parsed = parse_query(typed)

    assert parsed is not None
    assert _stored(language, stored_title) in _terms(parsed.match)


def test_stored_text_keeps_its_own_spelling() -> None:
    """LIB-7: the folding lives in the query, so stored text is not rewritten."""
    assert _stored(ItemLanguage.UZ_CYRL, "Қодирий") == "qodiriy"
    assert _stored(ItemLanguage.UZ_LATN, "Kodiriy") == "kodiriy"


def test_query_without_folded_letters_matches_as_typed() -> None:
    """LIB-7: a query with no folded letter adds nothing to the tsquery."""
    parsed = parse_query("Matn 10")

    assert parsed is not None
    assert parsed.match == parsed.tsquery


def test_spellings_put_the_text_first_and_are_capped() -> None:
    """LIB-7: the typed text is always tried; the spellings are bounded."""
    assert spellings("kodiriy")[0] == "kodiriy"
    assert set(spellings("kodiriy")) == {"kodiriy", "qodiriy"}
    assert len(spellings("k" * 30, limit=16)) == 16

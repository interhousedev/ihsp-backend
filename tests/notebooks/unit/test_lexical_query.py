"""NB-14: how a question becomes the `tsquery` texts of the passage search."""

from app.modules.notebooks.infrastructure.lexical_query import (
    MAX_TERMS,
    build_lexical_query,
    content_words,
)

import pytest


def test_content_words_are_lower_case_unique_and_at_least_three_letters() -> None:
    """NB-14: short words, stop words and repeats are dropped; order is kept."""
    words = content_words("Как происходит ФОТОСИНТЕЗ? Фотосинтез в листьях и на свету")

    assert words == ["происходит", "фотосинтез", "листьях", "свету"]


@pytest.mark.parametrize(
    "question", ["", "  ", "?!...", "a b", "как это что", "the and"]
)
def test_a_question_without_content_words_has_no_query(question: str) -> None:
    """NB-14: nothing to search for."""
    assert content_words(question) == []
    assert build_lexical_query(question) is None


def test_at_most_twelve_words_are_read() -> None:
    """NB-14: a long question is cut after twelve distinct content words."""
    question = " ".join(f"слово{n}" for n in range(30))

    assert content_words(question) == [f"слово{n}" for n in range(MAX_TERMS)]


def test_russian_words_get_an_exact_term_and_a_short_prefix_in_the_simple_query() -> (
    None
):
    """NB-14: the russian query stems in the database; simple adds a stem prefix."""
    query = build_lexical_query("фотосинтезе")

    assert query is not None
    assert query.russian == "фотосинтезе"
    assert query.simple == "фотосинтезе | фотосинт:*"


def test_uzbek_words_are_cut_to_about_half_so_endings_match_both_ways() -> None:
    """NB-14: "fotosintezda" and "fotosintezlarning" must reach "fotosintez"."""
    ending = build_lexical_query("fotosintezda")
    chain = build_lexical_query("fotosintezlarning")

    assert ending is not None and chain is not None
    assert "fotosin:*" in ending.simple.split(" | ")
    assert "fotosinte:*" in chain.simple.split(" | ")


def test_short_words_have_no_prefix_term() -> None:
    """NB-14: a prefix of a four-letter word would match too much."""
    query = build_lexical_query("suv daryo qum")

    assert query is not None
    assert query.simple == "suv | daryo | qum | daryo:*"


@pytest.mark.parametrize("apostrophe", ["'", "’", "‘", "`", "ʻ", "ʼ"])
def test_a_word_with_an_apostrophe_is_searched_in_every_spelling(
    apostrophe: str,
) -> None:
    """NB-14: oʻ is a letter for the parser, ' and ’ split the word; cover both."""
    query = build_lexical_query(f"o{apostrophe}simliklar")

    assert query is not None
    terms = query.russian.split(" | ")
    assert terms == ["oʻsimliklar", "oʼsimliklar", "simliklar"]


def test_the_word_regex_keeps_an_apostrophe_only_between_letters() -> None:
    """NB-14: a quote around a word is not part of it."""
    assert content_words("'fotosintez' g'oya o'") == ["fotosintez", "g'oya"]


def test_syntax_characters_never_reach_the_query_text() -> None:
    """NB-14: tsquery operators in a question are separators, not syntax."""
    query = build_lexical_query("a&b | !(fotosintez) :* <-> \\ ' \" ; --")

    assert query is not None
    assert query.russian == "fotosintez"
    assert not set("&!()<>\\\"';") & set(query.simple.replace(":*", ""))

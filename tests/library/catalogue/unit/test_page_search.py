"""In-item search: folding, locating a query on a page, the snippet."""

from app.modules.library.domain.page_search import fold_text, locate, snippet

import pytest


def test_fold_ignores_case_diacritics_and_yo() -> None:
    """`Ёлка`, `Élan` and `ЙОД` fold to `елка`, `elan`, `иод`."""
    assert fold_text("Ёлка  Élan\nЙОД") == "елка elan иод"


def test_locate_returns_whole_word_spans() -> None:
    """A hit inside a word covers the word; offsets index the page text."""
    text = "Force and acceleration\nare linked"
    [hit] = locate(text, "ACCELER", "en")
    assert text[hit.start : hit.end] == "acceleration"


def test_locate_several_words_and_limit() -> None:
    """A phrase matches across words; `limit` caps the hits."""
    text = "a b a b a b"
    assert len(locate(text, "a b", "en")) == 3
    assert len(locate(text, "a b", "en", limit=2)) == 2


@pytest.mark.parametrize(
    ("page", "query", "language"),
    [
        ("Ўзбекистон — бизнинг ватан", "o'zbekiston", "uz"),
        ("O‘zbekiston bizning vatan", "ЎЗБЕКИСТОН", "uz"),
        ("Ёж и ёлка", "елка", "ru"),
    ],
)
def test_locate_across_scripts_and_diacritics(
    page: str, query: str, language: str
) -> None:
    """Uzbek Cyrillic and Latin match each other; ё matches е."""
    assert locate(page, query, language)


def test_no_match_is_empty() -> None:
    """Nothing found, no hits."""
    assert locate("hello world", "xyz", "en") == []


def test_snippet_keeps_context() -> None:
    """Pre and post hold the neighbours, the match the hit, whitespace collapsed."""
    text = "x " * 80 + "target\nword " + "y " * 80
    [hit] = locate(text, "target", "en")
    found = snippet(text, hit.start, hit.end, context=10)
    assert found.match == "target"
    assert found.pre.startswith("…") and found.post.endswith("…")
    assert "\n" not in found.post

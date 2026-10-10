"""Name keys: Latin and Cyrillic spellings of one name meet on one key."""

from app.modules.library.domain.catalogue_labels import (
    MAX_TAGS,
    distinct_authors,
    distinct_tags,
)
from app.modules.library.domain.name_keys import clean_label, name_key

import pytest


@pytest.mark.parametrize(
    ("latin", "cyrillic"),
    [
        ("Navoiy", "Навои"),
        ("Alisher Navoiy", "Алишер Навои"),
        ("Abdulla Qodiriy", "Абдулла Кадыри"),
        ("Mahmudxo'ja Behbudiy", "Махмудхўжа Бехбудий"),
        ("Oʻtkir Hoshimov", "Ўткир Хошимов"),
        ("Pushkin", "Пушкин"),
        ("Dostoevskiy", "Достоевский"),
        ("Tolstoy", "Толстой"),
        ("Fizika", "Физика"),
        ("Matematika", "Математика"),
    ],
)
def test_latin_and_cyrillic_spellings_have_one_key(latin: str, cyrillic: str) -> None:
    """Uzbek and Russian transliterations of a name give the same key."""
    assert name_key(latin) == name_key(cyrillic)


def test_the_key_ignores_case_apostrophes_spaces_and_punctuation() -> None:
    """`Oʻ`, `O'`, `Oʼ` and `O‘` are the same; so are stray spaces and dots."""
    forms = [
        "O'tkir  Hoshimov",
        "oʻtkir hoshimov",
        "Oʼtkir Hoshimov.",
        "O‘tkir, Hoshimov",
    ]
    assert len({name_key(form) for form in forms}) == 1


def test_different_names_have_different_keys() -> None:
    """The fold is loose, not blind."""
    assert name_key("Alisher Navoiy") != name_key("Abdulla Qodiriy")
    assert name_key("Fizika") != name_key("Kimyo")


def test_nothing_to_key_is_empty() -> None:
    """Punctuation alone has no key (and so no author)."""
    assert name_key("  .. ,, ") == ""
    assert distinct_authors(["", "  ", "..."]) == []


def test_authors_are_distinct_by_key_and_keep_the_first_spelling() -> None:
    """Two spellings of one person count once; order is kept."""
    found = distinct_authors(["Alisher  Navoiy", "Алишер Навои", "Abdulla Qodiriy"])
    assert [name for name, _ in found] == ["Alisher Navoiy", "Abdulla Qodiriy"]


def test_tags_are_cut_and_capped() -> None:
    """A tag is at most 40 characters and an item has at most 20 tags."""
    names = [f"tag {number}" for number in range(MAX_TAGS + 5)]
    assert len(distinct_tags(names)) == MAX_TAGS
    assert len(distinct_tags(["x" * 100])[0][0]) == 40
    assert clean_label("  a   b  ") == "a b"

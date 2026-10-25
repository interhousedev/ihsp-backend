"""Transliteration and normalization."""

from app.shared.text import normalize_group_name, slugify, title_case, transliterate

import pytest


def test_group_name_is_normalized_to_latin_upper_case() -> None:
    """EMIS group '2ТН2' becomes '2TN2'."""
    assert normalize_group_name("2ТН2") == "2TN2"
    assert normalize_group_name("2 тн 2") == "2TN2"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Кластер", "klaster"), ("Room 102", "room-102"), ("  A -- b  ", "a-b")],
)
def test_slugify_gives_a_lowercase_latin_slug(value: str, expected: str) -> None:
    """ROOM-1: slugs are letters, digits and single hyphens."""
    assert slugify(value) == expected


def test_title_case_fixes_upper_case_emis_names() -> None:
    """EMIS sends 'ALEKSEY'."""
    assert title_case("ALEKSEY") == "Aleksey"
    assert title_case("  aleksey ") == "Aleksey"


def test_transliterate_keeps_case_and_other_characters() -> None:
    """Uzbek letters map to their Latin forms."""
    assert transliterate("Щука-ҳ") == "SHuka-h"
    assert transliterate("abc 123") == "abc 123"

"""PWA-3: dotted version numbers are parsed and compared segment by segment."""

from app.shared.versions import compare_versions, parse_version

import pytest


@pytest.mark.parametrize(
    ("text", "parts"),
    [
        ("1", (1,)),
        ("1.4", (1, 4)),
        ("1.4.2", (1, 4, 2)),
        ("0.0.0", (0, 0, 0)),
        ("10.20.30", (10, 20, 30)),
    ],
)
def test_a_version_is_its_integer_segments(text: str, parts: tuple[int, ...]) -> None:
    """PWA-3: "1.4.2" is (1, 4, 2)."""
    assert parse_version(text) == parts


@pytest.mark.parametrize(
    "text",
    ["", "abc", "1.", ".1", "1..2", "-1", "1.-2", "1.0-beta", "v1.0", " 1.0", "1 .0"],
)
def test_anything_but_dotted_non_negative_integers_is_rejected(text: str) -> None:
    """PWA-3: no letters, signs, blanks or empty segments."""
    with pytest.raises(ValueError, match="version"):
        parse_version(text)


def test_non_ascii_digits_are_rejected() -> None:
    """PWA-3: Arabic-Indic digits are not release numbers."""
    with pytest.raises(ValueError, match="version"):
        parse_version("1.٣")


def test_numeric_comparison_beats_text_comparison() -> None:
    """PWA-3: "1.10.0" is newer than "1.9.0", though "1.1" sorts before "1.9"."""
    assert compare_versions("1.10.0", "1.9.0") == 1
    assert compare_versions("1.9.0", "1.10.0") == -1


def test_missing_segments_count_as_zero() -> None:
    """PWA-3: "1.4" equals "1.4.0" and "1" equals "1.0.0"."""
    assert compare_versions("1.4", "1.4.0") == 0
    assert compare_versions("1", "1.0.0") == 0
    assert compare_versions("1.4", "1.4.1") == -1
    assert compare_versions("1.4.1", "1.4") == 1


def test_equal_versions_compare_equal() -> None:
    """PWA-3: the same text is the same version."""
    assert compare_versions("2.0.1", "2.0.1") == 0


def test_the_major_segment_wins() -> None:
    """PWA-3: 2.0.0 is newer than 1.99.99."""
    assert compare_versions("2.0.0", "1.99.99") == 1


def test_comparing_an_invalid_version_raises() -> None:
    """PWA-3: garbage on either side is an error, not an ordering."""
    with pytest.raises(ValueError, match="version"):
        compare_versions("abc", "1.0.0")
    with pytest.raises(ValueError, match="version"):
        compare_versions("1.0.0", "1.x")

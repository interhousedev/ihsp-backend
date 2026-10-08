"""Slug, title and invite code rules of a course (LMS-3, UF-LMS-06)."""

from app.modules.lms.domain.authoring.course_rules import (
    clean_title,
    new_invite_code,
    validate_slug,
)
from app.modules.lms.domain.authoring.errors import SlugInvalidError, TitleInvalidError
from app.shared.ids import SHORT_ID_ALPHABET

import pytest


@pytest.mark.parametrize("slug", ["abc", "calculus-1", "a" * 60, "2024-math"])
def test_valid_slugs_are_accepted(slug: str) -> None:
    """Slugs are `[a-z0-9-]{3,60}`."""
    assert validate_slug(slug) == slug


@pytest.mark.parametrize("slug", ["ab", "a" * 61, "Calculus", "calc_1", "кластер", ""])
def test_invalid_slugs_are_rejected(slug: str) -> None:
    """Uppercase, underscores, non-Latin letters and bad lengths are refused."""
    with pytest.raises(SlugInvalidError):
        validate_slug(slug)


def test_title_is_trimmed_and_limited() -> None:
    """A title has 1-200 characters after trimming."""
    assert clean_title("  Calculus  ") == "Calculus"
    with pytest.raises(TitleInvalidError):
        clean_title("   ")
    with pytest.raises(TitleInvalidError):
        clean_title("x" * 201)


def test_invite_code_has_10_characters_from_the_short_id_alphabet() -> None:
    """LMS-3: 10 random characters (about 58 bits)."""
    codes = {new_invite_code() for _ in range(50)}

    assert len(codes) == 50
    assert all(len(c) == 10 and set(c) <= set(SHORT_ID_ALPHABET) for c in codes)

"""TMP-1: the rules of a temporary mark value and comment."""

from app.modules.academic.domain.classwork.errors import (
    TemporaryMarkCommentInvalidError,
    TemporaryMarkValueInvalidError,
)
from app.modules.academic.domain.classwork.temporary_mark import (
    COMMENT_MAX,
    MARK_SCALE,
    clean_comment,
    ensure_value,
)

import pytest


def test_scale_is_the_emis_scale() -> None:
    """TMP-1: the values are those EMIS stores (2 to 5)."""
    assert MARK_SCALE == (2, 3, 4, 5)
    assert [ensure_value(v) for v in MARK_SCALE] == [2, 3, 4, 5]


@pytest.mark.parametrize("value", [0, 1, 6, 10, -3, True])
def test_values_off_the_scale_are_refused(value: int) -> None:
    """TMP-1: anything else is a validation error."""
    with pytest.raises(TemporaryMarkValueInvalidError):
        ensure_value(value)


def test_comment_is_stripped_and_blank_is_none() -> None:
    """TMP-1: an optional comment."""
    assert clean_comment(None) is None
    assert clean_comment("   ") is None
    assert clean_comment("  oral answer ") == "oral answer"


def test_long_comment_is_refused() -> None:
    """TMP-1: at most COMMENT_MAX characters."""
    assert clean_comment("x" * COMMENT_MAX) == "x" * COMMENT_MAX
    with pytest.raises(TemporaryMarkCommentInvalidError):
        clean_comment("x" * (COMMENT_MAX + 1))

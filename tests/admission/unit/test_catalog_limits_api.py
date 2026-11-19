"""Supplement prompt limits on catalog proposals: unit, minimum, choice group."""

from datetime import date

from app.modules.admission.application.supp_prompts import clean_proposed
from app.modules.admission.domain.errors import ValidationFailedError
from app.modules.admission.domain.supp_prompts import limits_error

import pytest

TODAY = date(2026, 11, 19)


def _item(**extra: object) -> dict[str, object]:
    base: dict[str, object] = {
        "cycle": "2026-27",
        "prompt": "Describe a community.",
        "word_limit": 250,
        "required": True,
        "source_url": "https://example.edu/apply",
    }
    base.update(extra)
    return base


def test_limit_defaults_are_words_without_minimum_or_group() -> None:
    """ADM-CAT-API-LIMITS: an item without limit fields keeps the words default."""
    out = clean_proposed([_item()], TODAY)
    assert out[0]["limit_unit"] == "words"
    assert out[0]["limit_min"] is None
    assert out[0]["choice_group"] is None


def test_characters_limit_accepts_up_to_30000() -> None:
    """ADM-CAT-API-LIMITS: 200 characters and 30000 characters are valid."""
    out = clean_proposed(
        [_item(word_limit=200, limit_unit="characters", limit_min=None)], TODAY
    )
    assert out[0]["limit_unit"] == "characters"
    assert out[0]["word_limit"] == 200
    assert limits_error("characters", 30000, None, None) is None


@pytest.mark.parametrize(
    ("unit", "word_limit", "field"),
    [
        ("words", 5001, "word_limit"),
        ("characters", 30001, "word_limit"),
        ("pages", 10, "limit_unit"),
    ],
)
def test_out_of_range_limit_is_rejected(unit: str, word_limit: int, field: str) -> None:
    """ADM-CAT-API-LIMITS: the bound depends on the unit."""
    assert limits_error(unit, word_limit, None, None) == field
    with pytest.raises(ValidationFailedError) as err:
        clean_proposed([_item(word_limit=word_limit, limit_unit=unit)], TODAY)
    assert err.value.params == {"field": field}


def test_minimum_must_fit_under_the_limit() -> None:
    """ADM-CAT-API-LIMITS: limit_min above word_limit, or without one, is invalid."""
    assert limits_error("words", 400, 500, None) == "limit_min"
    assert limits_error("words", None, 100, None) == "limit_min"
    assert limits_error("words", 500, 400, None) is None


def test_choice_group_is_trimmed_and_blank_becomes_none() -> None:
    """ADM-CAT-API-LIMITS: a blank group is stored as no group."""
    out = clean_proposed([_item(choice_group="   ")], TODAY)
    assert out[0]["choice_group"] is None
    out = clean_proposed([_item(choice_group=" Essay A ")], TODAY)
    assert out[0]["choice_group"] == "Essay A"


def test_choice_group_length_is_capped() -> None:
    """ADM-CAT-API-LIMITS: groups longer than 40 characters are rejected."""
    with pytest.raises(ValidationFailedError) as err:
        clean_proposed([_item(choice_group="x" * 41)], TODAY)
    assert err.value.params == {"field": "choice_group"}

"""Password policy (ID-10): length and character classes."""

from app.modules.identity.domain.password_policy import check_password

import pytest


def test_strong_password_has_no_errors() -> None:
    assert check_password("AdminDemo1") == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Ab1", ["id-password-too-short"]),
        ("Abcdefgh", ["id-password-no-digit"]),
        ("abcdefg1", ["id-password-no-upper"]),
        ("ABCDEFG1", ["id-password-no-lower"]),
    ],
)
def test_each_broken_rule_gives_its_key(value: str, expected: list[str]) -> None:
    assert check_password(value) == expected


def test_all_broken_rules_are_reported_together() -> None:
    assert check_password("") == [
        "id-password-too-short",
        "id-password-no-digit",
        "id-password-no-upper",
        "id-password-no-lower",
    ]


def test_exactly_eight_characters_are_long_enough() -> None:
    assert "id-password-too-short" not in check_password("Abcdef1!")

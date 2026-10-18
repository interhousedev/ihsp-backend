"""Custom fields: definitions are checked, values are checked per kind (CF-*)."""

from app.modules.certificates.domain.custom_fields import (
    CustomField,
    FieldKind,
    check_fields,
    clean_values,
)
from app.modules.certificates.domain.errors import (
    CertificateInvalidError,
    CustomFieldInvalidError,
    CustomFieldRequiredError,
)
from app.modules.certificates.domain.type_rules import apply_changes
from tests.certificates.conftest import make_type

import pytest

LABEL = {"uz": "Yo'nalish", "ru": "Направление", "en": "Track"}


def field(key: str = "track", kind: FieldKind = FieldKind.SINGLE, **over: object):
    """A custom field with sensible defaults for the tests."""
    values: dict[str, object] = {
        "key": key,
        "kind": kind,
        "label": LABEL,
        "options": (
            ("math", "art") if kind in (FieldKind.SINGLE, FieldKind.MULTI) else ()
        ),
    }
    values.update(over)
    return CustomField(**values)  # type: ignore[arg-type]


def test_a_well_formed_field_list_passes() -> None:
    """CF-01: text, number, single and multi fields with options pass the check."""
    check_fields(
        [
            field("note", FieldKind.TEXT),
            field("score", FieldKind.NUMBER),
            field("track", FieldKind.SINGLE, allow_other=True),
            field("langs", FieldKind.MULTI),
        ]
    )


@pytest.mark.parametrize(
    "fields",
    [
        [field("Bad-Key", FieldKind.TEXT)],
        [field("a", FieldKind.TEXT), field("a", FieldKind.NUMBER)],
        [field("track", FieldKind.SINGLE, options=())],
        [field("track", FieldKind.SINGLE, options=("x", "x"))],
        [field("note", FieldKind.TEXT, options=("x",))],
        [field("note", FieldKind.TEXT, label={"uz": "a", "ru": "б", "en": ""})],
        [field(f"k{i}", FieldKind.TEXT) for i in range(21)],
    ],
)
def test_an_unusable_field_list_is_refused(fields: list[CustomField]) -> None:
    """CF-02: bad keys, duplicates, empty or stray options and missing labels."""
    with pytest.raises(CertificateInvalidError):
        check_fields(fields)


def test_a_type_change_applies_custom_fields() -> None:
    """CF-03: the type keeps the fields, given as dicts from the HTTP body."""
    kind = make_type("sat")
    apply_changes(
        kind,
        {
            "custom_fields": [
                {
                    "key": "track",
                    "kind": "single",
                    "label": LABEL,
                    "required": True,
                    "options": ["math"],
                    "allow_other": True,
                }
            ]
        },
    )

    [item] = kind.custom_fields
    assert (item.key, item.kind, item.required, item.allow_other) == (
        "track",
        FieldKind.SINGLE,
        True,
        True,
    )


@pytest.mark.parametrize(
    ("kind", "raw", "expected"),
    [
        (FieldKind.TEXT, {"note": "  hi  "}, {"note": "hi"}),
        (FieldKind.TEXT, {"note": "   "}, {}),
        (FieldKind.NUMBER, {"score": 3}, {"score": 3.0}),
        (FieldKind.SINGLE, {"track": "art"}, {"track": "art"}),
        (
            FieldKind.MULTI,
            {"track": ["art", "math", "art"]},
            {"track": ["art", "math"]},
        ),
        (FieldKind.MULTI, {"track": []}, {}),
    ],
)
def test_valid_values_are_cleaned(
    kind: FieldKind, raw: dict[str, object], expected: dict[str, object]
) -> None:
    """CF-04: values are trimmed, numbers are floats, multi lists de-duplicated."""
    key = next(iter(raw))
    fields = [field(key, kind)]

    assert clean_values(fields, raw) == expected


@pytest.mark.parametrize(
    ("kind", "raw"),
    [
        (FieldKind.NUMBER, {"score": "3"}),
        (FieldKind.NUMBER, {"score": True}),
        (FieldKind.NUMBER, {"score": float("inf")}),
        (FieldKind.SINGLE, {"track": "chess"}),
        (FieldKind.MULTI, {"track": "art"}),
        (FieldKind.TEXT, {"track": "x" * 256}),
    ],
)
def test_invalid_values_are_refused(kind: FieldKind, raw: dict[str, object]) -> None:
    """CF-05: wrong type, undefined choice (no other), or too long text."""
    key = next(iter(raw))

    with pytest.raises(CustomFieldInvalidError):
        clean_values([field(key, kind)], raw)


def test_free_text_is_allowed_only_with_other() -> None:
    """CF-06: an undefined choice is stored as other text when allow_other is on."""
    fields = [field("track", FieldKind.SINGLE, allow_other=True)]

    assert clean_values(fields, {"track": "Chess club"}) == {"track": "Chess club"}


def test_a_required_field_needs_a_value() -> None:
    """CF-07: a required field with nothing sent is refused; optional is skipped."""
    required = field("track", FieldKind.SINGLE, required=True)

    with pytest.raises(CustomFieldRequiredError):
        clean_values([required], {})
    assert clean_values([field("track")], {}) == {}


def test_unknown_keys_are_dropped() -> None:
    """CF-08: keys the type does not define never reach the entry."""
    assert clean_values([field("track")], {"track": "art", "other": "x"}) == {
        "track": "art"
    }

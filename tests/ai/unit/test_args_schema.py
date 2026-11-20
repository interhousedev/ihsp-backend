"""The small validator of AI request arguments."""

from app.modules.ai.domain.args_schema import validate_args

SCHEMA = {
    "type": "object",
    "properties": {
        "language": {"type": "string", "enum": ["uz", "ru", "en"]},
        "count": {"type": "integer", "minimum": 1, "maximum": 50},
        "tags": {"type": "array", "items": {"type": "string"}},
        "note": {"type": "string", "maxLength": 5},
    },
    "required": ["language"],
    "additionalProperties": False,
}


def test_valid_arguments_have_no_problems() -> None:
    """A conforming object passes."""
    assert validate_args(SCHEMA, {"language": "uz", "count": 3, "tags": ["a"]}) == []


def test_missing_required_and_unknown_fields_are_reported() -> None:
    """Missing, unknown, wrong type, enum and range errors name the field."""
    problems = validate_args(SCHEMA, {"count": 0, "extra": 1})
    assert "language: required" in problems
    assert "extra: not allowed" in problems
    assert "count: below minimum 1" in problems


def test_types_enum_length_and_items_are_checked() -> None:
    """Booleans are not integers; enum, maxLength and array items apply."""
    problems = validate_args(
        SCHEMA,
        {"language": "de", "count": True, "tags": [1], "note": "too long"},
    )
    assert "language: not one of ['uz', 'ru', 'en']" in problems
    assert "count: expected integer" in problems
    assert "tags[0]: expected string" in problems
    assert "note: longer than 5" in problems


def test_empty_schema_accepts_any_object() -> None:
    """A request without declared arguments takes none or any."""
    assert validate_args({}, {"x": 1}) == []

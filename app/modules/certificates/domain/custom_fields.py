"""Custom input fields a certificate type defines, and the values students give."""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.modules.certificates.domain.errors import (
    CertificateInvalidError,
    CustomFieldInvalidError,
    CustomFieldRequiredError,
)

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
MAX_FIELDS = 20
MAX_OPTIONS = 50
MAX_OPTION_LEN = 120
MAX_LABEL_LEN = 120
MAX_TEXT = 255
LOCALES = ("uz", "ru", "en")


class FieldKind(StrEnum):
    """What a custom field holds."""

    TEXT = "text"
    NUMBER = "number"
    SINGLE = "single"
    MULTI = "multi"


CHOICE_KINDS = (FieldKind.SINGLE, FieldKind.MULTI)


@dataclass(frozen=True, slots=True)
class CustomField:
    """One field of a type: its label per locale, kind, and choices when it has them."""

    key: str
    kind: FieldKind
    label: dict[str, str]
    required: bool = False
    options: tuple[str, ...] = ()
    allow_other: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON form stored on the type."""
        return {
            "key": self.key,
            "kind": self.kind.value,
            "label": dict(self.label),
            "required": self.required,
            "options": list(self.options),
            "allow_other": self.allow_other,
        }


def field_from_dict(raw: Mapping[str, Any]) -> CustomField:
    """Build a field from its JSON form; an unknown kind is a type error."""
    try:
        kind = FieldKind(str(raw.get("kind", "")))
    except ValueError:
        raise CertificateInvalidError(params={"field": "custom_fields"}) from None
    return CustomField(
        key=str(raw.get("key", "")),
        kind=kind,
        label={str(k): str(v) for k, v in dict(raw.get("label") or {}).items()},
        required=bool(raw.get("required", False)),
        options=tuple(str(o) for o in raw.get("options") or ()),
        allow_other=bool(raw.get("allow_other", False)),
    )


def check_fields(fields: list[CustomField]) -> None:
    """Reject a field list whose keys, labels or choices are unusable."""
    if len(fields) > MAX_FIELDS:
        raise _type_error()
    keys = [f.key for f in fields]
    if len(set(keys)) != len(keys):
        raise _type_error()
    for item in fields:
        _check_field(item)


def _check_field(item: CustomField) -> None:
    if not KEY_RE.match(item.key):
        raise _type_error()
    for locale in LOCALES:
        title = item.label.get(locale, "").strip()
        if not title or len(title) > MAX_LABEL_LEN:
            raise _type_error()
    if item.kind not in CHOICE_KINDS:
        if item.options or item.allow_other:
            raise _type_error()
        return
    options = item.options
    if not options or len(options) > MAX_OPTIONS or len(set(options)) != len(options):
        raise _type_error()
    if any(not o.strip() or len(o) > MAX_OPTION_LEN for o in options):
        raise _type_error()


def _type_error() -> CertificateInvalidError:
    return CertificateInvalidError(params={"field": "custom_fields"})


def clean_values(
    fields: list[CustomField], raw: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Check the student's values against the fields; unknown keys are dropped."""
    given = raw or {}
    cleaned: dict[str, Any] = {}
    for item in fields:
        value = _clean_one(item, given.get(item.key))
        if value is None:
            if item.required:
                raise CustomFieldRequiredError(params={"field": item.key})
            continue
        cleaned[item.key] = value
    return cleaned


def _clean_one(item: CustomField, value: Any) -> Any:
    if value is None or value == "" or value == []:
        return None
    if item.kind is FieldKind.NUMBER:
        return _number(item, value)
    if item.kind is FieldKind.MULTI:
        if not isinstance(value, list) or len(value) > MAX_OPTIONS:
            raise CustomFieldInvalidError(params={"field": item.key})
        picked = [_choice(item, v) for v in value]
        unique = list(dict.fromkeys(v for v in picked if v is not None))
        return unique or None
    if item.kind is FieldKind.SINGLE:
        return _choice(item, value)
    return _text(item, value)


def _text(item: CustomField, value: Any) -> str | None:
    if not isinstance(value, str):
        raise CustomFieldInvalidError(params={"field": item.key})
    cleaned = value.strip()
    if len(cleaned) > MAX_TEXT:
        raise CustomFieldInvalidError(params={"field": item.key})
    return cleaned or None


def _number(item: CustomField, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CustomFieldInvalidError(params={"field": item.key})
    number = float(value)
    if not math.isfinite(number):
        raise CustomFieldInvalidError(params={"field": item.key})
    return number


def _choice(item: CustomField, value: Any) -> str | None:
    text = _text(item, value)
    if text is None:
        return None
    if text in item.options:
        return text
    if item.allow_other:
        return text
    raise CustomFieldInvalidError(params={"field": item.key})

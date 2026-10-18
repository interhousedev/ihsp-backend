"""Rules for creating and editing certificate types."""

import re
from collections.abc import Mapping
from typing import Any

from app.modules.certificates.domain.certificate_type import (
    LOCALES,
    TYPE_FIELDS,
    CertificateType,
)
from app.modules.certificates.domain.custom_fields import (
    CustomField,
    check_fields,
    field_from_dict,
)
from app.modules.certificates.domain.errors import (
    CertificateInvalidError,
    CertificateTypeBuiltinError,
)

CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,39}$")
MAX_NAME_LEN = 120


def _fail(field_name: str) -> CertificateInvalidError:
    return CertificateInvalidError(params={"field": field_name})


def check_type(kind: CertificateType) -> None:
    """Reject a type whose code, names, levels or range are unusable."""
    if not CODE_RE.match(kind.code):
        raise _fail("code")
    for locale in LOCALES:
        title = kind.name.get(locale, "").strip()
        if not title or len(title) > MAX_NAME_LEN:
            raise _fail("name")
    check_fields(kind.custom_fields)


def apply_changes(kind: CertificateType, changes: Mapping[str, Any]) -> None:
    """Set the changed fields; a built-in type keeps its code."""
    for key, value in changes.items():
        if key not in TYPE_FIELDS:
            continue
        if key == "code" and kind.builtin and value != kind.code:
            raise CertificateTypeBuiltinError()
        if key == "custom_fields":
            value = [_as_field(item) for item in value or []]
        setattr(kind, key, value)
    check_type(kind)


def _as_field(item: CustomField | Mapping[str, Any]) -> CustomField:
    return item if isinstance(item, CustomField) else field_from_dict(item)

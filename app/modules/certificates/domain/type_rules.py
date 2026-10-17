"""Rules for creating and editing certificate types."""

import re
from collections.abc import Mapping
from typing import Any

from app.modules.certificates.domain.certificate_type import (
    LOCALES,
    TYPE_FIELDS,
    CertificateType,
)
from app.modules.certificates.domain.errors import (
    CertificateInvalidError,
    CertificateTypeBuiltinError,
)

CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,39}$")
MAX_LEVELS = 40
MAX_LEVEL_LEN = 20
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
    levels = kind.levels
    if len(levels) > MAX_LEVELS or len(set(levels)) != len(levels):
        raise _fail("levels")
    if any(not item or len(item) > MAX_LEVEL_LEN for item in levels):
        raise _fail("levels")
    low, high = kind.score_min, kind.score_max
    if low is not None and high is not None and low > high:
        raise _fail("score_max")


def apply_changes(kind: CertificateType, changes: Mapping[str, Any]) -> None:
    """Set the changed fields; a built-in type keeps its code."""
    for key, value in changes.items():
        if key not in TYPE_FIELDS:
            continue
        if key == "code" and kind.builtin and value != kind.code:
            raise CertificateTypeBuiltinError()
        setattr(kind, key, value)
    check_type(kind)

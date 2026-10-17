"""Applying student input to an entry, checked against its type."""

from collections.abc import Mapping
from typing import Any

from app.modules.certificates.domain.certificate_type import CertificateType
from app.modules.certificates.domain.entry import CertificateEntry
from app.modules.certificates.domain.validation import (
    check_level,
    check_percent,
    check_score,
    check_text,
    check_year,
    clean_text,
)

TEXT_FIELDS = ("level", "subject", "serial")
NUMBER_FIELDS = ("score", "percent", "year")
EDITABLE = (*TEXT_FIELDS, *NUMBER_FIELDS)


def apply_values(
    kind: CertificateType, entry: CertificateEntry, values: Mapping[str, Any]
) -> None:
    """Set the given fields on the entry after checking all of them for the type."""
    for key in EDITABLE:
        if key not in values:
            continue
        value = values[key]
        setattr(entry, key, clean_text(value) if key in TEXT_FIELDS else value)
    check_level(kind, entry.level)
    check_score(kind, entry.score)
    check_percent(entry.percent)
    check_year(entry.year)
    check_text("subject", entry.subject)
    check_text("serial", entry.serial)

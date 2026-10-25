"""Applying student input to an entry, checked against its type."""

from collections.abc import Mapping
from typing import Any

from app.modules.certificates.domain.certificate_type import CertificateType
from app.modules.certificates.domain.custom_fields import clean_values
from app.modules.certificates.domain.entry import CertificateEntry


def apply_values(
    kind: CertificateType, entry: CertificateEntry, values: Mapping[str, Any]
) -> None:
    """Set the custom values on the entry, checked against the type's fields."""
    if "custom" in values:
        entry.custom_values = clean_values(kind.custom_fields, values["custom"])

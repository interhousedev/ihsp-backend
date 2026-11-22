"""The curator's card of an institution: stored facts as editable input."""

import datetime as dt
from dataclasses import dataclass
from typing import Any, Final

from app.modules.admission.domain.intl_facts import FACT_SPECS
from app.shared.base_error import ValidationFailedError

LOCALES: Final = ("uz", "ru", "en")
DESCRIPTION_MAX: Final = 2000
SCHOLARSHIP_WRITE: Final = (
    "name",
    "provider",
    "country",
    "basis",
    "coverage_pct_min",
    "coverage_pct_max",
    "covers",
    "url",
    "cycle",
)
"""Scholarship columns a curator writes through the card."""


@dataclass(frozen=True, slots=True)
class CardFact:
    """One stored fact in the shape the editor sends back (`clean_facts` input)."""

    key: str
    value: Any
    source_url: str | None
    year: int | None
    note: str | None
    verified: bool
    updated_at: dt.datetime | None = None


def fact_input(key: str, value: Any, unit: str | None) -> Any:
    """Turn a stored value and unit into the value `clean_facts` accepts."""
    spec = FACT_SPECS.get(key)
    if spec is None:
        return value
    if spec.kind == "money":
        return {"amount": value, "currency": unit}
    return value


def clean_description(raw: dict[str, Any]) -> dict[str, str] | None:
    """Trim per-locale text; unknown locales or oversize text fail, empty is None."""
    out: dict[str, str] = {}
    for locale, text in raw.items():
        if locale not in LOCALES or not isinstance(text, str):
            raise ValidationFailedError(params={"field": "description"})
        text = text.strip()
        if len(text) > DESCRIPTION_MAX:
            raise ValidationFailedError(params={"field": "description"})
        if text:
            out[locale] = text
    return out or None

"""Admission rate of an institution and the safety/target thresholds."""

import math
from typing import Final

from app.modules.admission.domain.chooser import CatalogInstitution

SAFETY_RATE: Final = 0.6
TARGET_RATE: Final = 0.2
"""Rates (0..1) from which an institution is a safety and a target."""
RATE_FACTS: Final = ("acceptance_rate_international", "acceptance_rate")


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float | str):
        try:
            number = float(value)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def admission_rate(inst: CatalogInstitution) -> float | None:
    """Published acceptance rate as 0..1, the international cohort first.

    The fact is a percent range (`min`/`max`); unparsable edges are ignored and
    a fact without a usable edge counts as unknown.
    """
    for key in RATE_FACTS:
        f = inst.fact(key)
        if f is None or not isinstance(f.value, dict):
            continue
        edges = [
            n
            for v in (f.value.get("min"), f.value.get("max"))
            if (n := _number(v)) is not None
        ]
        if edges:
            return max(0.0, min(1.0, sum(edges) / len(edges) / 100))
    return None

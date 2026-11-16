"""Rule-based admission estimates as ranges (§11.3). Pure and deterministic."""

from dataclasses import dataclass, field
from typing import Any

from app.modules.admission.domain.chooser import CatalogInstitution

METHOD_VERSION = "baseline-1"
BASE_WIDTH = 10
"""Half-width in percentage points of the range for a fresh published rate."""
STALE_WIDTH = 10
"""Extra half-width when the rate is older than `STALE_YEARS`."""
STALE_YEARS = 2
LOW_RATE = 15
LOW_RATE_CAP = 25
LOWER_CLAMP, UPPER_CLAMP = 1, 95
SAFETY_LOW, SAFETY_CENTRE = 60, 50
TARGET_CENTRE = 25


@dataclass(frozen=True, slots=True)
class Estimate:
    """A range with its basis; `label` is unknown when facts are missing."""

    label: str
    low: int | None = None
    high: int | None = None
    basis: dict[str, Any] = field(default_factory=dict)
    caveats: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    method_version: str = METHOD_VERSION
    calibrated: bool = False


def _rate(inst: CatalogInstitution) -> tuple[float | None, dict[str, Any]]:
    for key, cohort in (
        ("acceptance_rate_international", "international"),
        ("acceptance_rate", "all"),
    ):
        f = inst.fact(key)
        if f is None or not isinstance(f.value, dict):
            continue
        lo, hi = f.value.get("min"), f.value.get("max")
        vals = [float(v) for v in (lo, hi) if isinstance(v, int | float)]
        if not vals:
            continue
        basis = {"cohort": cohort, "cycle": f.year, "source_url": f.source_url}
        return sum(vals) / len(vals), basis
    return None, {}


def estimate(
    inst: CatalogInstitution, affordability: str, current_year: int
) -> Estimate:
    """Range and label from the published acceptance rate and affordability.

    Without a rate, or for an unreviewed institution, there is no range and the
    label is `unknown`: nothing is computed from null facts.
    """
    centre, basis = _rate(inst)
    if centre is None:
        return Estimate("unknown", missing=("acceptance_rate",))
    if not inst.verified:
        return Estimate("unknown", basis=basis, caveats=("unverified",))
    caveats: list[str] = []
    width = BASE_WIDTH
    year = basis.get("cycle")
    if year is None or current_year - int(year) > STALE_YEARS:
        width += STALE_WIDTH
        caveats.append("stale")
    low = max(LOWER_CLAMP, round(centre - width))
    high = min(UPPER_CLAMP, round(centre + width))
    if centre < LOW_RATE:
        high = min(high, LOW_RATE_CAP)
        caveats.append("reach_for_everyone")
    basis = {**basis, "acceptance_rate": round(centre, 1)}
    if low >= SAFETY_LOW and centre >= SAFETY_CENTRE and affordability == "feasible":
        label = "safety"
    elif centre >= TARGET_CENTRE and low < SAFETY_LOW or centre >= SAFETY_CENTRE:
        label = "target"
    else:
        label = "reach"
    return Estimate(label, low, high, basis, tuple(caveats))

"""Who sees an estimate range (§11.3): the visibility wrapper of the baseline."""

from dataclasses import dataclass, field
from typing import Any

from app.modules.admission.domain.chooser import CatalogInstitution, ListEntry
from app.modules.admission.domain.estimates import Estimate


@dataclass(frozen=True, slots=True)
class EstimateView:
    """An estimate as one viewer may see it; `low`/`high` are None when hidden."""

    label: str
    low: int | None
    high: int | None
    range_visible: bool
    calibrated: bool
    label_overridden: bool
    verified: bool
    caveats: tuple[str, ...]
    missing: tuple[str, ...]
    method_version: str
    sources: tuple[str, ...] = field(default=())
    basis: dict[str, Any] = field(default_factory=dict)


def view_estimate(
    est: Estimate,
    inst: CatalogInstitution,
    entry: ListEntry,
    *,
    owner: bool,
    staff_uncalibrated: bool,
    student_visible: bool,
) -> EstimateView:
    """Hide the range from a student unless the setting allows it (§11.3).

    Staff with `estimates:view_uncalibrated` always see it, marked uncalibrated.
    A counselor's label override wins over the computed label.
    """
    show = staff_uncalibrated or (owner and student_visible)
    sources = tuple(
        sorted({f.source_url for f in inst.facts.values() if f.source_url is not None})
    )
    return EstimateView(
        label=entry.label_override or est.label,
        low=est.low if show else None,
        high=est.high if show else None,
        range_visible=show,
        calibrated=est.calibrated,
        label_overridden=entry.label_override is not None,
        verified=inst.verified,
        caveats=est.caveats,
        missing=est.missing,
        method_version=est.method_version,
        sources=sources,
        basis=est.basis if show else {},
    )

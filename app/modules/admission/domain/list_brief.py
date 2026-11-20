"""Candidates for the list brief: catalog institutions that fit as safety or target.

The role of a candidate comes from the same published data and student signals as
the labels of the list (`classify`), never from the model; the model only writes
the text around them.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from app.modules.admission.domain.budget import AdmitRate, admit_rate_of
from app.modules.admission.domain.chooser import CatalogInstitution
from app.modules.admission.domain.classification import (
    Balance,
    StudentSignals,
    classify,
)
from app.modules.admission.domain.estimates import estimate

MAX_CANDIDATES: Final = 8
ROLES: Final = ("safety", "target")


@dataclass(frozen=True, slots=True)
class BriefCandidate:
    """A catalog institution and the role it would play on this student's list."""

    institution: CatalogInstitution
    role: str
    admit_rate: AdmitRate | None


def needed_role(balance: Balance) -> str:
    """The role the list lacks most.

    Safety when there is none or the list is reach-heavy, else target.
    """
    if balance.safety == 0 or balance.status in ("no_safety", "too_many_reach"):
        return "safety"
    return "target"


def brief_candidates(
    catalog: Iterable[CatalogInstitution],
    on_list: set[object],
    balance: Balance,
    signals: StudentSignals | None,
    year: int,
    limit: int = MAX_CANDIDATES,
) -> list[BriefCandidate]:
    """Up to `limit` off-list institutions that fit as safety or target.

    Institutions with a published rate come first when their computed role is
    safety or target (the needed role, then the higher admit rate, then name).
    The catalog publishes few rates, so when that leaves room the list is filled
    with reviewed institutions whose rate is unknown: they take the needed role
    and the cheaper ones come first, because cost is the one thing known about them.
    """
    need = needed_role(balance)
    rated: list[BriefCandidate] = []
    unrated: list[BriefCandidate] = []
    for inst in catalog:
        if inst.id in on_list or not inst.verified:
            continue
        rate = admit_rate_of(
            inst.fact("intl_acceptance_rate"), inst.fact("acceptance_rate")
        )
        if rate is None:
            unrated.append(BriefCandidate(inst, need, None))
            continue
        label = classify(
            inst,
            estimate(inst, "unknown", year).label,
            signals,
            bucket=None,
            override=None,
        ).effective
        if label in ROLES:
            rated.append(BriefCandidate(inst, label, rate))
    rated.sort(
        key=lambda c: (
            c.role != need,
            -(c.admit_rate.percent if c.admit_rate else -1.0),
            c.institution.name.casefold(),
        )
    )
    unrated.sort(key=lambda c: (_cost(c.institution), c.institution.name.casefold()))
    return (rated + unrated)[:limit]


def _cost(inst: CatalogInstitution) -> float:
    """Yearly cost known for the institution; unknown sorts last."""
    if inst.coa_total is not None:
        return float(inst.coa_total)
    f = inst.fact("intl_tuition_usd")
    if f is not None and isinstance(f.value, int | float):
        return float(f.value)
    return float("inf")

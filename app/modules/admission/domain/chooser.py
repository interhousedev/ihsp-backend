"""Catalog and list read models of the university chooser (§11)."""

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

BINDING_ROUNDS = frozenset({"ED", "ED2"})
UNRESOLVED_AFFORDABILITY = ("gap", "unknown")
"""Rounds in which an accepted offer binds the applicant (§12.3)."""


@dataclass(frozen=True, slots=True)
class FactView:
    """A published catalog fact with its source; `verified` means reviewed."""

    value: Any
    source_url: str | None = None
    year: int | None = None
    note: str | None = None
    verified: bool = False


@dataclass(frozen=True, slots=True)
class CatalogInstitution:
    """An institution with its facts, flattened for the chooser."""

    id: UUID
    slug: str | None
    name: str
    country: str
    city: str | None
    status: str
    facts: dict[str, FactView] = field(default_factory=dict)
    coa_total: Decimal | None = None
    coa_currency: str | None = None
    aid_basis: str | None = None
    merit_available: bool | None = None
    scholarship_count: int = 0
    logo_url: str | None = None
    cover_url: str | None = None

    @property
    def verified(self) -> bool:
        """Published by a reviewer (seed rows marked verified)."""
        return self.status == "published"

    def fact(self, key: str) -> FactView | None:
        """Return a fact with a non-null value."""
        f = self.facts.get(key)
        return f if f is not None and f.value is not None else None

    @property
    def fields(self) -> list[str]:
        """Fields of study the institution lists."""
        f = self.fact("fields")
        return [str(x) for x in f.value] if f is not None else []


@dataclass(frozen=True, slots=True)
class CatalogScholarship:
    """A scholarship of an institution or a national programme."""

    id: UUID
    name: str
    provider: str
    institution_id: UUID | None
    country: str | None
    basis: str
    coverage_min: int | None
    coverage_max: int | None
    covers: tuple[str, ...]
    url: str | None
    status: str
    cycle: int | None


@dataclass(frozen=True, slots=True)
class CatalogFilters:
    """Chooser filters; a filter on a missing fact excludes the institution."""

    q: str | None = None
    country: str | None = None
    field: str | None = None
    city_type: str | None = None
    study_type: str | None = None
    max_crime_index: float | None = None
    aid: str | None = None
    scholarships: bool | None = None
    max_cost: Decimal | None = None


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fact_matches(inst: CatalogInstitution, f: CatalogFilters) -> bool:
    for key, want in (("city_type", f.city_type), ("study_type", f.study_type)):
        if want:
            got = inst.fact(key)
            if got is None or str(got.value) != want:
                return False
    if f.max_crime_index is not None:
        got = inst.fact("crime_index")
        n = _num(got.value) if got is not None else None
        if n is None or n > f.max_crime_index:
            return False
    return True


def _money_matches(inst: CatalogInstitution, f: CatalogFilters) -> bool:
    if f.aid and inst.aid_basis != f.aid:
        return False
    if f.scholarships is not None and (inst.scholarship_count > 0) != f.scholarships:
        return False
    return f.max_cost is None or not (
        inst.coa_total is None
        or inst.coa_currency != "USD"
        or inst.coa_total > f.max_cost
    )


def matches(inst: CatalogInstitution, f: CatalogFilters) -> bool:
    """Whether the institution passes every set filter."""
    if f.q and f.q.casefold() not in inst.name.casefold():
        return False
    if f.country and inst.country != f.country.upper():
        return False
    if f.field and f.field.casefold() not in {x.casefold() for x in inst.fields}:
        return False
    return _fact_matches(inst, f) and _money_matches(inst, f)


@dataclass(frozen=True, slots=True)
class ListEntry:
    """One institution on a student's list."""

    id: UUID
    student_id: UUID
    institution_id: UUID
    round: str = "RD"
    status: str = "considering"
    bucket: str | None = None
    notes: str | None = None
    label_override: str | None = None
    override_note: str | None = None
    override_by: UUID | None = None
    override_at: dt.datetime | None = None
    affordability_status: str = "unknown"
    lock_version: int = 1


@dataclass(frozen=True, slots=True)
class AffordabilityCheck:
    """The affordability arithmetic of a list entry (yearly amounts)."""

    list_entry_id: UUID
    coa_total: Decimal | None
    confirmed_aid: Decimal | None
    estimated_aid: Decimal | None
    gap: Decimal | None
    status: str
    requested_sign_off_at: dt.datetime | None = None
    signed_off_by: UUID | None = None
    signed_off_at: dt.datetime | None = None
    sign_off_note: str | None = None


_EDGE = re.compile(r"^(\d+)(k?)$")


def _edge(token: str) -> Decimal | None:
    m = _EDGE.match(token)
    if m is None:
        return None
    return Decimal(int(m.group(1)) * (1000 if m.group(2) else 1))


def budget_upper(band: str | None) -> Decimal | None:
    """Upper edge (per year) of a budget band id such as `5k_15k`; None if open.

    `under_5k` is 5000, `5k_15k` is 15000, `over_50k` has no upper edge.
    """
    if not band or band.startswith("over_"):
        return None
    return _edge(band.rsplit("_", 1)[-1])


def check_affordability(
    band: str | None,
    coa_total: Decimal | None,
    confirmed_aid: Decimal | None = None,
) -> tuple[str, Decimal | None]:
    """Return (status, gap) of a yearly cost against the stated budget band.

    `unknown` when the band or the cost is missing (never computed from null
    facts); `over_*` bands have no upper edge and count as feasible.
    """
    if not band or coa_total is None:
        return "unknown", None
    if band.startswith("over_"):
        return "feasible", Decimal(0)
    upper = budget_upper(band)
    if upper is None:
        return "unknown", None
    gap = coa_total - (confirmed_aid or Decimal(0)) - upper
    if gap > 0:
        return "gap", gap
    return "feasible", Decimal(0)


def needs_affordability_gate(round_: str, status: str) -> bool:
    """A binding round with an unresolved cost gap or unknown cost is blocked."""
    return round_ in BINDING_ROUNDS and status in UNRESOLVED_AFFORDABILITY

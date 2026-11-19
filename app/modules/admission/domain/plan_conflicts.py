"""Conflicting early-application plans on a student's list (warn only).

An unknown policy never means "no conflict": when the facts that decide a
restriction are missing the finding is a `check`, not silence.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

Severity = Literal["conflict", "check"]

RESTRICTIVE: Final = frozenset({"REA", "SCEA"})
"""Single-choice early rounds: no other private US early plan is allowed."""
EARLY: Final = frozenset({"EA", "ED"})


@dataclass(frozen=True, slots=True)
class PlanEntry:
    """What the rules need of a list entry; `None` means the fact is unknown."""

    id: UUID
    round: str
    country: str | None = None
    institution_type: str | None = None


@dataclass(frozen=True, slots=True)
class PlanConflict:
    """One finding: a stable code, its severity and the entries involved."""

    code: str
    severity: Severity
    entry_ids: tuple[UUID, ...]


def _private_us(e: PlanEntry) -> bool | None:
    """True/False when known, None when the country or type is unknown."""
    if e.country is not None and e.country.upper() != "US":
        return False
    if e.institution_type is not None and e.institution_type != "private":
        return False
    if e.country is None or e.institution_type is None:
        return None
    return True


def _ids(entries: Iterable[PlanEntry]) -> tuple[UUID, ...]:
    return tuple(e.id for e in entries)


def plan_conflicts(entries: Iterable[PlanEntry]) -> tuple[PlanConflict, ...]:
    """Findings for the entries of one cycle; never blocks anything."""
    items = list(entries)
    by = {r: [e for e in items if e.round == r] for r in ("ED", "ED2", "EA")}
    restrictive = [e for e in items if e.round in RESTRICTIVE]
    out: list[PlanConflict] = []
    if len(by["ED"]) > 1:
        out.append(PlanConflict("multiple_ed", "conflict", _ids(by["ED"])))
    if by["ED"] and restrictive:
        out.append(
            PlanConflict(
                "ed_with_restrictive", "conflict", _ids([*by["ED"], *restrictive])
            )
        )
    if len(restrictive) > 1:
        out.append(PlanConflict("multiple_restrictive", "conflict", _ids(restrictive)))
    if len(by["ED2"]) > 1:
        out.append(PlanConflict("multiple_ed2", "conflict", _ids(by["ED2"])))
    if restrictive:
        out.extend(_early_conflicts(restrictive, by["EA"]))
    return tuple(out)


def _early_conflicts(
    restrictive: list[PlanEntry], early: list[PlanEntry]
) -> list[PlanConflict]:
    # ED is already reported by ed_with_restrictive whatever its country.
    sure: list[PlanEntry] = []
    unsure: list[PlanEntry] = []
    for e in early:
        verdict = _private_us(e)
        if verdict is True:
            sure.append(e)
        elif verdict is None:
            unsure.append(e)
    out: list[PlanConflict] = []
    if sure:
        out.append(
            PlanConflict(
                "restrictive_with_early", "conflict", _ids([*restrictive, *sure])
            )
        )
    if unsure:
        out.append(
            PlanConflict(
                "restrictive_with_early", "check", _ids([*restrictive, *unsure])
            )
        )
    return out

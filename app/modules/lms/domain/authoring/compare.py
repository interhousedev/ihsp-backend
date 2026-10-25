"""Comparing two course versions by revision IDs (LMS-11)."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.lms.domain.authoring.enums import StepChange
from app.modules.lms.domain.authoring.manifest import ManifestStep


@dataclass(frozen=True, slots=True)
class CompareRow:
    """How one step differs between versions A and B."""

    step_id: UUID
    title: str
    change: StepChange
    revision_a: UUID | None
    revision_b: UUID | None


def compare_manifests(
    a: Sequence[ManifestStep], b: Sequence[ManifestStep]
) -> list[CompareRow]:
    """Compare per step: same revision is `same`, otherwise changed/added/removed.

    Rows follow the outline order of B; steps only in A come last in A's order.
    """
    in_a = {s.step_id: s for s in a}
    in_b = {s.step_id: s for s in b}
    rows = [_row(in_a.get(s.step_id), s) for s in b]
    rows.extend(_row(s, None) for s in a if s.step_id not in in_b)
    return rows


def _row(a: ManifestStep | None, b: ManifestStep | None) -> CompareRow:
    present = b or a
    if present is None:  # pragma: no cover - callers pass at least one side
        raise ValueError("a comparison row needs at least one side")
    if a is None:
        change = StepChange.ADDED
    elif b is None:
        change = StepChange.REMOVED
    elif a.revision_id == b.revision_id:
        change = StepChange.SAME
    else:
        change = StepChange.CHANGED
    return CompareRow(
        step_id=present.step_id,
        title=present.title,
        change=change,
        revision_a=a.revision_id if a else None,
        revision_b=b.revision_id if b else None,
    )

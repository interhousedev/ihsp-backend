"""Pending changes: the difference between the draft and the live version."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.lms.domain.authoring.enums import StepChange, StepVia
from app.modules.lms.domain.authoring.manifest import ManifestStep
from app.modules.lms.domain.authoring.outline import Outline, step_ids_in


@dataclass(frozen=True, slots=True)
class StepSnapshot:
    """The hashes of one step that decide whether it is pending."""

    step_id: UUID
    title: str
    draft_hash: str
    live_hash: str | None
    live_revision_id: UUID | None
    via: StepVia


@dataclass(frozen=True, slots=True)
class PendingStep:
    """One pending step change."""

    step_id: UUID
    title: str
    change: StepChange
    via_mcp: bool
    via_ai: bool = False


@dataclass(frozen=True, slots=True)
class Pending:
    """All pending changes of a course."""

    draft_seq: int
    outline_changed: bool
    steps: tuple[PendingStep, ...]

    @property
    def is_empty(self) -> bool:
        """Return True when the draft equals the live version."""
        return not self.steps and not self.outline_changed

    @property
    def count(self) -> int:
        """Number of pending changes shown in the editor header.

        A restructure of the outline counts as one change only when no added or
        removed step already explains it.
        """
        explained = any(
            s.change in (StepChange.ADDED, StepChange.REMOVED) for s in self.steps
        )
        extra = 1 if self.outline_changed and not explained else 0
        return len(self.steps) + extra

    def of(self, change: StepChange) -> list[PendingStep]:
        """Pending steps of one kind."""
        return [s for s in self.steps if s.change == change]


def compute_pending(
    *,
    draft_seq: int,
    outline_hash: str,
    live_outline_hash: str | None,
    outline: Outline,
    snapshots: Mapping[UUID, StepSnapshot],
    live: Sequence[ManifestStep],
) -> Pending:
    """Compare the draft with the live version using hashes only.

    A step in the draft outline is `added` when it has no live revision and
    `changed` when its draft hash differs from the live hash; a step in the live
    manifest that is not in the draft outline is `removed`.
    """
    in_outline = step_ids_in(outline)
    steps: list[PendingStep] = []
    for step_id in in_outline:
        snap = snapshots.get(step_id)
        if snap is None:
            continue
        if snap.live_revision_id is None:
            change = StepChange.ADDED
        elif snap.draft_hash != snap.live_hash:
            change = StepChange.CHANGED
        else:
            continue
        steps.append(
            PendingStep(
                step_id,
                snap.title,
                change,
                via_mcp=snap.via is StepVia.MCP,
                via_ai=snap.via is StepVia.AI,
            )
        )
    present = set(in_outline)
    steps.extend(
        PendingStep(m.step_id, m.title, StepChange.REMOVED, via_mcp=False)
        for m in live
        if m.step_id not in present
    )
    return Pending(
        draft_seq=draft_seq,
        outline_changed=outline_hash != live_outline_hash,
        steps=tuple(steps),
    )

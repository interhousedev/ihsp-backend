"""Section mastery from best test scores, and the mastery unlock chain."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class StepPoints:
    """The test points of one live step for one learner."""

    step_id: UUID
    title: str
    max_points: Decimal
    best_points: Decimal | None
    completed: bool

    @property
    def best_pct(self) -> int | None:
        """Return the best share in percent, or None without tests or attempts."""
        if self.max_points <= 0 or self.best_points is None:
            return None
        return min(100, int(self.best_points * 100 / self.max_points))


@dataclass(frozen=True, slots=True)
class SectionMastery:
    """Mastery of one section and whether the learner may open it."""

    section_id: str
    title: str
    mastery_pct: int | None
    unlocked: bool
    steps: tuple[StepPoints, ...]


def section_pct(steps: Sequence[StepPoints]) -> int | None:
    """Return earned over possible points in percent; None without tests."""
    total = sum((s.max_points for s in steps), Decimal(0))
    if total <= 0:
        return None
    earned = sum(
        (min(s.best_points or Decimal(0), s.max_points) for s in steps), Decimal(0)
    )
    return int(earned * 100 / total)


def mastery_map(
    sections: Sequence[tuple[str, str, Sequence[StepPoints]]],
    threshold: int | None,
) -> list[SectionMastery]:
    """Return section mastery; a section opens when the previous one is mastered.

    Sections without tests count as mastered; the first section is always open.
    """
    result: list[SectionMastery] = []
    unlocked = True
    for section_id, title, steps in sections:
        pct = section_pct(steps)
        result.append(SectionMastery(section_id, title, pct, unlocked, tuple(steps)))
        if threshold is not None and pct is not None and pct < threshold:
            unlocked = False
    return result


def locked_step_ids(sections: Sequence[SectionMastery]) -> set[UUID]:
    """Return the steps of locked sections."""
    return {s.step_id for sec in sections if not sec.unlocked for s in sec.steps}


def best_by_step(
    best: Mapping[tuple[UUID, str], Decimal], step_id: UUID, block_ids: Sequence[str]
) -> Decimal | None:
    """Return the summed best points of a step's test blocks, None if no attempts."""
    values = [best[(step_id, b)] for b in block_ids if (step_id, b) in best]
    return sum(values, Decimal(0)) if values else None

"""The live version of a course: its manifest and the cached student render.

A published version is an immutable manifest of ``{step_id, revision_id, title}``
entries (README → Course versioning); revisions never change, so their student
render is cached in process memory by revision id (LMS-14, step 5 of the design).
"""

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID

from app.modules.lms.domain.authoring.manifest import parse_manifest as parse_sections
from app.modules.lms.domain.step_content import (
    FlashcardsBlock,
    StepContent,
    TestBlock,
)
from app.modules.lms.domain.student_render import render_step

RENDER_CACHE_SIZE: Final = 512

StepChange = Literal["new", "changed"]


@dataclass(frozen=True, slots=True)
class LiveStep:
    """One step of a version, pinned to a revision."""

    section_id: str
    step_id: UUID
    revision_id: UUID
    title: str


@dataclass(frozen=True, slots=True)
class LiveSection:
    """One section of a version."""

    id: str
    title: str
    steps: tuple[LiveStep, ...]


@dataclass(frozen=True, slots=True)
class LiveManifest:
    """The outline of a published version."""

    sections: tuple[LiveSection, ...]

    def steps(self) -> list[LiveStep]:
        """Return every step in outline order."""
        return [step for section in self.sections for step in section.steps]

    def step_ids(self) -> list[UUID]:
        """Return every step id in outline order."""
        return [step.step_id for step in self.steps()]

    def find(self, step_id: UUID) -> LiveStep | None:
        """Return the entry of a step, or None if the version does not contain it."""
        for step in self.steps():
            if step.step_id == step_id:
                return step
        return None


def parse_manifest(raw: Any) -> LiveManifest:  # noqa: ANN401 - stored JSON
    """Read the stored outline of a version with the authoring side's reader."""
    return LiveManifest(
        sections=tuple(
            LiveSection(
                id=section.id,
                title=section.title,
                steps=tuple(
                    LiveStep(
                        section_id=step.section_id,
                        step_id=step.step_id,
                        revision_id=step.revision_id,
                        title=step.title,
                    )
                    for step in section.steps
                ),
            )
            for section in parse_sections(raw)
        )
    )


def changes_between(old: LiveManifest, new: LiveManifest) -> dict[UUID, StepChange]:
    """Return the steps of ``new`` that are new or pinned to another revision.

    Used for the "new" and "changed" marks after a course update (UF-LMS-05).
    """
    before = {step.step_id: step.revision_id for step in old.steps()}
    result: dict[UUID, StepChange] = {}
    for step in new.steps():
        if step.step_id not in before:
            result[step.step_id] = "new"
        elif before[step.step_id] != step.revision_id:
            result[step.step_id] = "changed"
    return result


# - - - Student render and its cache - - -


@dataclass(frozen=True, slots=True)
class RenderedRevision:
    """The student render of one revision plus the ids learners need often.

    ``blocks`` must be deep-copied before it is filled with per-student data.
    """

    revision_id: UUID
    title: str
    blocks: tuple[dict[str, Any], ...]
    test_block_ids: tuple[str, ...]
    card_ids: Mapping[str, tuple[str, ...]]


def render_revision(revision_id: UUID, content: StepContent) -> RenderedRevision:
    """Render a revision for students (no correct answers, no explanations)."""
    rendered = render_step(content, revision_id=str(revision_id))
    return RenderedRevision(
        revision_id=revision_id,
        title=str(rendered["title"]),
        blocks=tuple(rendered["blocks"]),
        test_block_ids=tuple(
            block.id for block in content.blocks if isinstance(block, TestBlock)
        ),
        card_ids={
            block.id: tuple(card.id for card in block.cards)
            for block in content.blocks
            if isinstance(block, FlashcardsBlock)
        },
    )


class RenderCache:
    """In-process LRU of student renders keyed by revision id (512 entries)."""

    def __init__(self, capacity: int = RENDER_CACHE_SIZE) -> None:
        """Create an empty cache."""
        self._capacity = capacity
        self._items: OrderedDict[UUID, RenderedRevision] = OrderedDict()

    def get(self, revision_id: UUID) -> RenderedRevision | None:
        """Return the cached render and mark it as recently used."""
        item = self._items.get(revision_id)
        if item is not None:
            self._items.move_to_end(revision_id)
        return item

    def put(self, item: RenderedRevision) -> None:
        """Store a render, dropping the least recently used one when full."""
        self._items[item.revision_id] = item
        self._items.move_to_end(item.revision_id)
        while len(self._items) > self._capacity:
            self._items.popitem(last=False)

    def __len__(self) -> int:
        """Return the number of cached renders."""
        return len(self._items)

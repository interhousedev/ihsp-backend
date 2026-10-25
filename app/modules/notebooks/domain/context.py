"""The context pack: the passages a model call sees, with their labels (§ 3.3.2)."""

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from app.modules.notebooks.domain.enums import SourceKind

ContextMode = Literal["full", "retrieval", "sample"]


def make_label(source_n: int, seq: int) -> str:
    """Return the label shown to the model: ``S{n}:P{seq}``."""
    return f"S{source_n}:P{seq}"


@dataclass(frozen=True, slots=True)
class PackPassage:
    """A passage with the label it has in this request."""

    label: str
    passage_id: UUID
    source_id: UUID
    seq: int
    text: str
    token_estimate: int
    page: int | None = None
    heading: str | None = None


@dataclass(frozen=True, slots=True)
class PackSource:
    """A selected source: ``n`` is its position among the request's sources."""

    n: int
    source_id: UUID
    title: str
    kind: SourceKind
    passages: tuple[PackPassage, ...]
    guide_summary: str | None = None  # added in retrieval mode


@dataclass(frozen=True, slots=True)
class CourseContext:
    """The LMS course a workspace belongs to, as the model sees it (not a source).

    ``outline`` is the draft outline as indented plain text (sections, steps with ids);
    ``step`` is the current draft text of the step a lesson is written for, if any.
    """

    title: str
    description: str
    outline: str
    step_title: str | None = None
    step_text: str | None = None


@dataclass(frozen=True, slots=True)
class ContextPack:
    """What goes into the ``<sources>`` message of one request."""

    sources: tuple[PackSource, ...]
    mode: ContextMode
    token_estimate: int
    labels: dict[str, PackPassage] = field(default_factory=dict)  # "S1:P4" -> passage
    source_map: dict[str, UUID] = field(default_factory=dict)  # "S1" -> source id
    titles: dict[UUID, tuple[str, SourceKind]] = field(default_factory=dict)
    course: CourseContext | None = None  # set for course workspaces only

    @property
    def retrieval(self) -> bool:
        """True when only the most relevant parts were sent."""
        return self.mode == "retrieval"

    @property
    def sampled(self) -> bool:
        """True when a Studio sample was used (large notebook)."""
        return self.mode == "sample"

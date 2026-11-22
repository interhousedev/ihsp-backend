"""Essay reviews: one base review of the essay, one review per university.

The base review judges the essay on its own, against the rubric and the
closest published exemplars. A university review judges how the essay fits
that university's sourced mission, values and supplemental prompts. Several
universities mean one base review plus one review per university; an
unchanged input is served from the stored copy without a model call.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

ReviewKind = Literal["check", "base", "uni", "deep"]
Alignment = Literal["strong", "partial", "missing"]

REVIEW_KINDS: Final[tuple[ReviewKind, ...]] = ("check", "base", "uni", "deep")
ALIGNMENTS: Final[tuple[Alignment, ...]] = ("strong", "partial", "missing")
MAX_UNIVERSITIES: Final = 5
MAX_LIST: Final = 3
REVIEW_MIN_WORDS: Final = 50


@dataclass(frozen=True, slots=True)
class EssayInput:
    """The essay text a review reads."""

    kind: str
    title: str
    prompt_text: str
    word_limit: int | None
    body: str


@dataclass(frozen=True, slots=True)
class UniGoal:
    """One sourced goal of a university: mission, value or admission factor."""

    key: str
    text: str
    source_url: str | None


@dataclass(frozen=True, slots=True)
class UniContext:
    """What a university review compares the essay with."""

    institution_id: UUID
    name: str
    country: str
    goals: tuple[UniGoal, ...]
    supplements: tuple[str, ...]

    @property
    def sourced(self) -> bool:
        """True when there is at least one sourced goal or supplement."""
        return bool(self.goals or self.supplements)


@dataclass(frozen=True, slots=True)
class DimensionScore:
    """One rubric dimension scored 0 to 5 with a verbatim quote."""

    key: str
    score: int
    quote: str | None
    comment: str


@dataclass(frozen=True, slots=True)
class ParagraphNote:
    """A note on one paragraph; `paragraph` is 1-based."""

    paragraph: int
    note: str


@dataclass(frozen=True, slots=True)
class ExemplarPattern:
    """A pattern a published exemplar shows that the draft could use."""

    exemplar_id: UUID
    title: str
    school_name: str
    source_url: str
    pattern: str


@dataclass(frozen=True, slots=True)
class BaseReview:
    """The review of the essay on its own."""

    score: int
    band: str
    dimensions: tuple[DimensionScore, ...]
    summary: str
    strengths: tuple[str, ...]
    improvements: tuple[str, ...]
    paragraphs: tuple[ParagraphNote, ...]
    patterns: tuple[ExemplarPattern, ...]
    word_count: int
    word_limit: int | None
    over_limit: bool
    generic: bool


@dataclass(frozen=True, slots=True)
class GoalAlignment:
    """How the essay meets one sourced goal of a university."""

    key: str
    goal: str
    source_url: str | None
    alignment: Alignment
    evidence: str | None
    suggestion: str


@dataclass(frozen=True, slots=True)
class AoReaction:
    """How an admissions officer of the university may react to the essay."""

    summary: str
    likely_positive: tuple[str, ...]
    likely_concerns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UniReview:
    """The review of the essay for one university; `alignment` is 0 to 100."""

    institution_id: UUID
    institution_name: str
    alignment: int
    goals: tuple[GoalAlignment, ...]
    fit_summary: str
    supplement_tips: tuple[str, ...]
    risks: tuple[str, ...]
    sourced: bool
    ao_reaction: AoReaction | None = None


@dataclass(frozen=True, slots=True)
class StoredReview:
    """A stored review result keyed by the digest of its input."""

    id: UUID
    essay_id: UUID
    student_id: UUID
    kind: ReviewKind
    institution_id: UUID | None
    input_digest: str
    payload: dict[str, Any]
    model: str
    prompt_ref: str
    created_at: datetime

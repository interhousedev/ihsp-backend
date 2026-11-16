"""Three-word state and stored AI reviews of the profile slice (§3.2, §9)."""

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Final, Literal
from uuid import UUID

WordsSource = Literal["ai", "manual", "mixed"]
SafetyFlag = Literal["none", "injection_suspected", "safeguarding"]
ReviewStatus = Literal["ready", "in_flight", "failed"]
ALIGNMENT: Final = "alignment"
MAX_CANDIDATES: Final = 8


@dataclass(slots=True)
class WordsState:
    """The confirmed words, their version and the last AI candidates."""

    student_id: UUID
    words: tuple[str, ...] = ()
    candidates: list[dict[str, Any]] = field(default_factory=list)
    source: WordsSource = "manual"
    version: int = 0
    confirmed_at: dt.datetime | None = None
    lock_version: int = 0


@dataclass(frozen=True, slots=True)
class ReviewRecord:
    """A stored AI review (here: the alignment map of one student)."""

    student_id: UUID
    target_kind: str
    target_id: UUID
    input_hash: str
    task: str
    prompt_version: str
    schema_version: str
    model: str | None = None
    rubric_version: str | None = None
    words_version: int | None = None
    grades: dict[str, Any] = field(default_factory=dict)
    overall: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    safety_flag: SafetyFlag = "none"
    status: ReviewStatus = "ready"
    id: UUID | None = None
    created_at: dt.datetime | None = None

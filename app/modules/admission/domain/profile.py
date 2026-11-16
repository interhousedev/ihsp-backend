"""Student profile, background answers, words and opt-ins (§2, §3.2)."""

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from app.modules.admission.domain.errors import AdmissionNotFoundError, CharLimitError
from app.modules.admission.domain.questions import QUESTION_SET_VERSION, question

Stage = Literal["setup", "words", "items", "chooser", "docs", "submitted"]
AccountKind = Literal["student", "alumni"]
WORDS_COUNT: Final = 3
WORD_MAX_CHARS: Final = 40


def char_count(text: str) -> int:
    """Count characters the way the UI does: NFC code points."""
    return len(unicodedata.normalize("NFC", text))


def ensure_max_chars(text: str, limit: int, field_name: str) -> str:
    """Return the NFC text, or raise `admission/char_limit`."""
    normalized = unicodedata.normalize("NFC", text)
    if len(normalized) > limit:
        raise CharLimitError(
            params={"field": field_name, "limit": limit, "count": len(normalized)}
        )
    return normalized


@dataclass(frozen=True, slots=True)
class OptIns:
    """Student-controlled switches."""

    mentee: bool = False
    alumni_contact: bool = False
    estimates_visible: bool = False


@dataclass(slots=True)
class AdmissionProfile:
    """One per student; `answers` maps question id to its JSON answer."""

    student_id: UUID
    account_kind: AccountKind = "student"
    stage: Stage = "setup"
    question_set_version: str = QUESTION_SET_VERSION
    answers: dict[str, Any] = field(default_factory=dict)
    words: tuple[str, ...] = ()
    opt_ins: OptIns = OptIns()
    setup_completed_at: datetime | None = None
    lock_version: int = 0

    def set_answer(self, question_id: str, value: Any) -> None:
        """Store one answer; unknown or disabled questions are refused."""
        q = question(question_id)
        if q is None or not q.enabled:
            raise AdmissionNotFoundError(params={"question": question_id})
        if q.max_length is not None and isinstance(value, str):
            value = ensure_max_chars(value, q.max_length, question_id)
        self.answers[question_id] = value

    def set_words(self, words: list[str]) -> None:
        """Set the three profile words."""
        cleaned = tuple(
            ensure_max_chars(w.strip(), WORD_MAX_CHARS, "words") for w in words
        )
        if len(cleaned) != WORDS_COUNT or any(not w for w in cleaned):
            raise CharLimitError(
                params={"field": "words", "limit": WORDS_COUNT, "count": len(cleaned)}
            )
        self.words = cleaned

    @property
    def words_set(self) -> bool:
        """Return whether the three words exist (AI item tasks need them)."""
        return len(self.words) == WORDS_COUNT

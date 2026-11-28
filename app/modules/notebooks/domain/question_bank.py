"""Question bank entries, keyed by EMIS subject and topic."""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

Difficulty = Literal["easy", "medium", "hard"]
Origin = Literal["ai", "teacher"]
Visibility = Literal["teacher", "subject"]

_SPACES = re.compile(r"\s+")
_TRAILING = re.compile(r"[\s.,;:!?]+$")


def question_key(text: str) -> str:
    """The duplicate key: case, spaces and trailing punctuation do not matter."""
    return _TRAILING.sub("", _SPACES.sub(" ", text.strip().casefold()))


@dataclass(frozen=True, slots=True)
class BankQuestion:
    """One question of the bank."""

    id: UUID
    owner_id: UUID
    emis_subject_id: int
    topic: str
    question: str
    answer: str
    options: tuple[str, ...]
    explanation: str | None
    difficulty: Difficulty
    origin: Origin
    visibility: Visibility
    created_at: datetime

"""Ports: profile, words and review storage."""

import datetime as dt
from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.profile import AdmissionProfile
from app.modules.admission.domain.profile_words import ReviewRecord, WordsState


class ProfileRepository(Protocol):
    """Profiles, the confirmed words and their history."""

    async def get(self, student_id: UUID) -> AdmissionProfile | None:
        """Return the profile, if it exists."""
        ...

    async def save(
        self, profile: AdmissionProfile, expected_lock: int | None
    ) -> AdmissionProfile:
        """Insert (expected None) or update; a stale lock raises a conflict."""
        ...

    async def get_words(self, student_id: UUID) -> WordsState | None:
        """Return the words state, if it exists."""
        ...

    async def save_words(
        self, state: WordsState, expected_lock: int | None, *, history: bool
    ) -> WordsState:
        """Insert or update; `history` also stores the set in the history."""
        ...


class ReviewRepository(Protocol):
    """Cached AI reviews."""

    async def find(
        self, target_kind: str, target_id: UUID, input_hash: str
    ) -> ReviewRecord | None:
        """Return the review of exactly this input."""
        ...

    async def latest(self, student_id: UUID, target_kind: str) -> ReviewRecord | None:
        """Return the newest ready review of the kind."""
        ...

    async def count_since(self, student_id: UUID, task: str, since: dt.datetime) -> int:
        """Count the student's reviews of a task made since `since`."""
        ...

    async def add(self, review: ReviewRecord) -> ReviewRecord:
        """Insert the review."""
        ...

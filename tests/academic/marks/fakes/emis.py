"""A scripted EmisSource for the marks tests."""

import datetime as dt
import hashlib
import json
from collections.abc import Sequence
from uuid import UUID

from app.shared.contracts.emis import (
    EmisMark,
    EmisMarkType,
    EmisProfile,
    EmisSubject,
    EmisSubjectRatings,
    EmisUnavailable,
)

MarkSpec = tuple[str, dt.date, int]


def make_ratings(
    emis_subject_id: int,
    semester: int,
    marks: Sequence[MarkSpec] = (),
    rating: int | None = None,
) -> EmisSubjectRatings:
    """Build a response whose hash follows its content."""
    canonical = json.dumps(
        [
            emis_subject_id,
            semester,
            rating,
            [[t, d.isoformat(), v] for t, d, v in marks],
        ]
    )
    return EmisSubjectRatings(
        emis_subject_id=emis_subject_id,
        semester=semester,
        semester_rating=rating,
        marks=tuple(EmisMark(EmisMarkType(t), d, v) for t, d, v in marks),
        payload_hash=hashlib.sha256(canonical.encode()).hexdigest(),
    )


class FakeEmis:
    """EmisSource that answers from tables and records every call."""

    def __init__(self) -> None:
        """Start with no data."""
        self.table: dict[tuple[int, int], EmisSubjectRatings] = {}
        self.profile_result: EmisProfile | None = None
        self.subjects_result: list[EmisSubject] = []
        self.error: Exception | None = None
        self.unavailable_for: set[UUID] = set()
        self.calls: list[tuple[str, int | None, int | None]] = []

    def set(self, ratings: EmisSubjectRatings) -> None:
        """Answer this (subject, semester) with the given response."""
        self.table[(ratings.emis_subject_id, ratings.semester)] = ratings

    def _check(self, user_id: UUID) -> None:
        """Raise the scripted failure, if any."""
        if self.error is not None:
            raise self.error
        if user_id in self.unavailable_for:
            raise EmisUnavailable()

    async def profile(self, user_id: UUID) -> EmisProfile:
        """Return the scripted profile."""
        self.calls.append(("profile", None, None))
        self._check(user_id)
        assert self.profile_result is not None, "profile not scripted"
        return self.profile_result

    async def subjects(self, user_id: UUID) -> list[EmisSubject]:
        """Return the scripted subjects."""
        self.calls.append(("subjects", None, None))
        self._check(user_id)
        return self.subjects_result

    async def ratings(
        self, user_id: UUID, emis_subject_id: int, semester: int
    ) -> EmisSubjectRatings:
        """Return the scripted ratings (empty when not scripted)."""
        self.calls.append(("ratings", emis_subject_id, semester))
        self._check(user_id)
        return self.table.get(
            (emis_subject_id, semester), make_ratings(emis_subject_id, semester)
        )

    def ratings_calls(self) -> int:
        """Count the ratings requests so far."""
        return sum(1 for name, _s, _m in self.calls if name == "ratings")

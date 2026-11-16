"""Ports of the full application review."""

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.app_review import AppReview


class AppReviewRepository(Protocol):
    """Stored review versions (each call is its own transaction)."""

    async def add(self, review: AppReview) -> AppReview:
        """Insert a new version; the repository assigns `version`."""
        ...

    async def get(self, review_id: UUID) -> AppReview | None:
        """Return one review."""
        ...

    async def list_for(self, student_id: UUID, *, limit: int = 20) -> list[AppReview]:
        """Return the student's reviews, newest first."""
        ...

    async def save(self, review: AppReview) -> None:
        """Update status, results and timestamps."""
        ...


@dataclass(frozen=True, slots=True)
class ReviewInputs:
    """What the section agents read, already reduced to AI-safe data.

    Every list holds `(ref, text)` pairs; `ref` is the evidence reference the
    agents may cite (for example `item:<id>`).
    """

    words: tuple[str, ...] = ()
    profile: list[tuple[str, str]] = field(default_factory=list)
    items: list[tuple[str, str]] = field(default_factory=list)
    essays: list[tuple[str, str]] = field(default_factory=list)
    courses: list[tuple[str, str]] = field(default_factory=list)
    universities: list[tuple[str, str]] = field(default_factory=list)
    readiness: list[tuple[str, str]] = field(default_factory=list)
    staff_visible: bool = True


class ReviewInputsLoader(Protocol):
    """Collects the application of one student."""

    async def load(self, student_id: UUID) -> ReviewInputs:
        """Return the review inputs."""
        ...

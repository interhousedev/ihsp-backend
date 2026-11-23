"""What course certificates need from the LMS: course facts and learner results."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CertificateSection:
    """A section of the live course version."""

    id: str
    title: str


@dataclass(frozen=True, slots=True)
class CertificateCourse:
    """A course as the certificates see it."""

    id: UUID
    title: str
    public: bool
    sections: tuple[CertificateSection, ...]


@dataclass(frozen=True, slots=True)
class LearnerSection:
    """Steps and points of one section over the steps the learner may open."""

    section_id: str
    steps_total: int
    steps_done: int
    points_total: Decimal
    points_earned: Decimal


@dataclass(frozen=True, slots=True)
class LearnerResult:
    """An enrolled learner's progress in the live version."""

    user_id: UUID
    progress_pct: int
    sections: tuple[LearnerSection, ...]


class CourseCertificateFacts(Protocol):
    """Read-only LMS facts; implemented by the LMS module."""

    async def course(self, course_id: UUID) -> CertificateCourse | None:
        """Return the course with its live sections (None when missing)."""
        ...

    async def learner(self, course_id: UUID, user_id: UUID) -> LearnerResult | None:
        """Return the learner's results (None when not enrolled or no live version)."""
        ...

    async def active_learners(self, course_id: UUID) -> list[UUID]:
        """Return the enrolled learners with some progress."""
        ...

    async def can_manage(self, user_id: UUID, course_id: UUID) -> bool:
        """Return whether the user may edit the course (and so its certificates)."""
        ...

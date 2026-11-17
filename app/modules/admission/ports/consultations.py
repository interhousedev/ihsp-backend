"""Ports: consultations, quiz answers, profile interests, issuing process."""

import datetime as dt
from collections.abc import Collection
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from app.modules.admission.domain.consultations import Consultation
from app.modules.admission.domain.profile_details import Interests, QuizAnswers
from app.modules.admission.ports.documents import (
    DocumentRepository,
    TranscriptRepository,
)
from app.modules.admission.ports.essays import EssayRepository
from app.modules.admission.ports.items import ItemRepository
from app.modules.admission.ports.profile import ProfileRepository
from app.modules.admission.ports.repositories import AccessRepository
from app.modules.admission.ports.staff import StaffRepository
from app.shared.notifications import NotificationDraft


class ConsultationRepository(Protocol):
    """Stored consultation requests."""

    async def add(self, c: Consultation) -> Consultation:
        """Insert a request."""
        ...

    async def get(self, consultation_id: UUID) -> Consultation | None:
        """Return the request."""
        ...

    async def save(self, c: Consultation) -> Consultation:
        """Update; a stale `lock_version` raises `admission/conflict`."""
        ...

    async def of_student(self, student_id: UUID) -> list[Consultation]:
        """The student's requests, newest first."""
        ...

    async def count_active(self, student_id: UUID) -> int:
        """Requests that are requested, proposed or accepted."""
        ...

    async def for_staff(
        self,
        kinds: Collection[str],
        staff_id: UUID,
        statuses: Collection[str],
        *,
        all_staff: bool = False,
    ) -> list[Consultation]:
        """Open requests of the kinds plus the ones assigned to the staff member.

        `all_staff` (administrators) lists every request in the statuses.
        """
        ...


class ProfileDetailsRepository(Protocol):
    """Stored interests and quiz answers."""

    async def get_interests(self, student_id: UUID) -> Interests:
        """Return the interests (empty when never saved)."""
        ...

    async def save_interests(
        self, student_id: UUID, interests: Interests, now: dt.datetime
    ) -> None:
        """Upsert the interests."""
        ...

    async def get_quiz(self, student_id: UUID, quiz: str) -> QuizAnswers | None:
        """Return the stored answers of a quiz."""
        ...

    async def save_quiz(self, answers: QuizAnswers, now: dt.datetime) -> None:
        """Upsert the answers of a quiz (whole replacement)."""
        ...

    async def completed_quizzes(self, student_id: UUID) -> frozenset[str]:
        """Quizzes the student finished."""
        ...


class _Tx(Protocol):
    async def __aenter__(self) -> Self:
        """Open the transaction."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Roll back unless committed."""
        ...

    async def commit(self) -> None:
        """Commit the transaction."""
        ...


class ConsultUnitOfWork(_Tx, Protocol):
    """The part of the unit of work the consultation service uses."""

    @property
    def consultations(self) -> ConsultationRepository:
        """Requests."""
        ...

    @property
    def access(self) -> AccessRepository:
        """The audit log."""
        ...

    @property
    def items(self) -> ItemRepository:
        """Projects and activities a request can link to."""
        ...

    @property
    def essays(self) -> EssayRepository:
        """Essays a request can link to."""
        ...

    @property
    def staff(self) -> StaffRepository:
        """Assignments, to find the counselors and mentors of a student."""
        ...

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications through the outbox."""
        ...


class DetailsUnitOfWork(_Tx, Protocol):
    """The part of the unit of work the profile-details service uses."""

    @property
    def profile_details(self) -> ProfileDetailsRepository:
        """Interests and quiz answers."""
        ...

    @property
    def profiles(self) -> ProfileRepository:
        """Profile and three words."""
        ...

    @property
    def items(self) -> ItemRepository:
        """Activities and projects."""
        ...


class ProcessUnitOfWork(_Tx, Protocol):
    """The part of the unit of work the issuing-process service uses."""

    @property
    def transcripts(self) -> TranscriptRepository:
        """Transcript requests."""
        ...

    @property
    def documents(self) -> DocumentRepository:
        """Uploaded documents."""
        ...

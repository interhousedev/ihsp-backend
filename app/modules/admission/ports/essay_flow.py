"""Ports of the essay flow: prompt catalog, practice, gallery, slots and vectors."""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.essay_categories import ShortAnswer
from app.modules.admission.domain.essay_flow import (
    GalleryEntry,
    GroupLabel,
    PracticeEntry,
    PromptRef,
    SlotAssignment,
    StoredIdeaFit,
)
from app.shared.contracts.embeddings import QueryVector


class PromptCatalog(Protocol):
    """The supplemental prompts of the catalog (latest cycle of each institution)."""

    async def all(self) -> list[PromptRef]:
        """The prompts of every non-archived institution, by name and position."""
        ...

    async def for_institution(self, institution_id: UUID) -> list[PromptRef]:
        """The prompts of one institution's latest cycle, by position."""
        ...


class PracticeRepository(Protocol):
    """A student's daily practice entries; body and evaluation are sealed."""

    async def get(self, student_id: UUID, day: dt.date) -> PracticeEntry | None:
        """The entry of the day, or None."""
        ...

    async def save(self, entry: PracticeEntry) -> PracticeEntry:
        """Insert the entry or replace the one of the same student and day."""
        ...

    async def recent(self, student_id: UUID, limit: int) -> list[PracticeEntry]:
        """The newest entries, latest day first."""
        ...

    async def days(self, student_id: UUID, limit: int) -> list[dt.date]:
        """The days with an entry, newest first (nothing is opened)."""
        ...


class GalleryRepository(Protocol):
    """Essay versions students published to each other."""

    async def get(self, essay_id: UUID) -> GalleryEntry | None:
        """The published entry of an essay, or None."""
        ...

    async def publish(self, entry: GalleryEntry) -> GalleryEntry:
        """Publish a version; a published essay moves to the new version."""
        ...

    async def unpublish(self, essay_id: UUID) -> None:
        """Take the essay out of the gallery (no error when it is not there)."""
        ...

    async def by_student(self, student_id: UUID) -> list[GalleryEntry]:
        """One student's published entries, newest first."""
        ...

    async def others(self, student_id: UUID, limit: int) -> list[GalleryEntry]:
        """The newest entries of every other student."""
        ...


class SlotRepository(Protocol):
    """Essays placed into the prompt slots of universities."""

    async def for_student(
        self, student_id: UUID, institution_id: UUID | None = None
    ) -> list[SlotAssignment]:
        """A student's slots, of one university or of all of them."""
        ...

    async def put(self, slot: SlotAssignment) -> None:
        """Place the essay; it leaves any other slot of the same university."""
        ...

    async def clear(self, student_id: UUID, institution_id: UUID, slot: str) -> None:
        """Empty one slot (no error when it is empty)."""
        ...


class ShortAnswerRepository(Protocol):
    """Sealed short texts per supplemental prompt."""

    async def for_student(self, student_id: UUID) -> list[ShortAnswer]:
        """All of a student's short answers."""
        ...

    async def get(self, student_id: UUID, prompt_key: str) -> ShortAnswer | None:
        """The answer to one prompt, or None."""
        ...

    async def put(self, answer: ShortAnswer) -> ShortAnswer:
        """Insert or replace the answer of the student and prompt."""
        ...


class GroupLabelRepository(Protocol):
    """Generated names of prompt groups, keyed by the digest of their members."""

    async def get_many(self, hashes: Sequence[str]) -> dict[str, GroupLabel]:
        """The stored labels among `hashes`."""
        ...

    async def put_many(self, labels: Sequence[GroupLabel]) -> None:
        """Store labels; one already stored for the same members is kept."""
        ...


class IdeaFitCache(Protocol):
    """Idea fits per student and idea text digest."""

    async def get(self, student_id: UUID, text_digest: str) -> StoredIdeaFit | None:
        """The cached fit of the idea, or None."""
        ...

    async def put(self, student_id: UUID, text_digest: str, fit: StoredIdeaFit) -> None:
        """Store or replace the fit of the idea."""
        ...


@dataclass(frozen=True, slots=True)
class VectorSet:
    """Vectors of texts, in the order asked, and the model that made them."""

    model: str
    vectors: list[list[float]]


class PromptVectors(Protocol):
    """Vectors of prompt texts and of a student's idea (vectors module)."""

    async def of_texts(self, texts: Sequence[str]) -> VectorSet | None:
        """Vectors of public texts; None when no embedding model is reachable."""
        ...

    async def of_query(self, text: str) -> QueryVector | None:
        """The vector of a student's text; None when unavailable."""
        ...

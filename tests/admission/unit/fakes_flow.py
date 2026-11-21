"""In-memory fakes of the essay flow ports."""

import datetime as dt
import hashlib
import math
from collections.abc import Iterable, Sequence
from dataclasses import replace
from typing import Any
from uuid import UUID

from app.modules.admission.domain.essay_flow import (
    GalleryEntry,
    PracticeEntry,
    PromptRef,
    SlotAssignment,
)
from app.modules.admission.ports.essay_flow import VectorSet
from app.shared.contracts.embeddings import QueryVector


class MemPrompts:
    """A prompt catalog over a list."""

    def __init__(self, refs: Sequence[PromptRef] = ()) -> None:
        self.refs = list(refs)

    async def all(self) -> list[PromptRef]:
        return list(self.refs)

    async def for_institution(self, institution_id: UUID) -> list[PromptRef]:
        return sorted(
            (r for r in self.refs if r.institution_id == institution_id),
            key=lambda r: r.position,
        )


class MemPractice:
    """Practice entries keyed by student and day."""

    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, dt.date], PracticeEntry] = {}

    async def get(self, student_id: UUID, day: dt.date) -> PracticeEntry | None:
        return self.rows.get((student_id, day))

    async def save(self, entry: PracticeEntry) -> PracticeEntry:
        old = self.rows.get((entry.student_id, entry.day))
        if old is not None:
            entry = replace(entry, id=old.id)
        self.rows[(entry.student_id, entry.day)] = entry
        return entry

    async def recent(self, student_id: UUID, limit: int) -> list[PracticeEntry]:
        mine = [e for (s, _), e in self.rows.items() if s == student_id]
        return sorted(mine, key=lambda e: e.day, reverse=True)[:limit]

    async def days(self, student_id: UUID, limit: int) -> list[dt.date]:
        return [e.day for e in await self.recent(student_id, limit)]


class MemGallery:
    """Published entries keyed by essay."""

    def __init__(self) -> None:
        self.rows: dict[UUID, GalleryEntry] = {}

    async def get(self, essay_id: UUID) -> GalleryEntry | None:
        return self.rows.get(essay_id)

    async def publish(self, entry: GalleryEntry) -> GalleryEntry:
        old = self.rows.get(entry.essay_id)
        if old is not None:
            entry = replace(entry, id=old.id)
        self.rows[entry.essay_id] = entry
        return entry

    async def unpublish(self, essay_id: UUID) -> None:
        self.rows.pop(essay_id, None)

    async def by_student(self, student_id: UUID) -> list[GalleryEntry]:
        return self._newest(r for r in self.rows.values() if r.student_id == student_id)

    async def others(self, student_id: UUID, limit: int) -> list[GalleryEntry]:
        rows = self._newest(r for r in self.rows.values() if r.student_id != student_id)
        return rows[:limit]

    @staticmethod
    def _newest(rows: Iterable[GalleryEntry]) -> list[GalleryEntry]:
        return sorted(
            rows,
            key=lambda r: r.published_at or dt.datetime.min.replace(tzinfo=dt.UTC),
            reverse=True,
        )


class MemSlots:
    """Slot assignments; an essay holds one slot per university."""

    def __init__(self) -> None:
        self.rows: list[SlotAssignment] = []

    async def for_student(
        self, student_id: UUID, institution_id: UUID | None = None
    ) -> list[SlotAssignment]:
        return [
            r
            for r in self.rows
            if r.student_id == student_id
            and (institution_id is None or r.institution_id == institution_id)
        ]

    async def put(self, slot: SlotAssignment) -> None:
        self.rows = [
            r
            for r in self.rows
            if not (
                r.student_id == slot.student_id
                and r.institution_id == slot.institution_id
                and (r.slot == slot.slot or r.essay_id == slot.essay_id)
            )
        ]
        self.rows.append(slot)

    async def clear(self, student_id: UUID, institution_id: UUID, slot: str) -> None:
        self.rows = [
            r
            for r in self.rows
            if (r.student_id, r.institution_id, r.slot)
            != (student_id, institution_id, slot)
        ]


def bag_vector(text: str, dims: int = 64) -> list[float]:
    """A bag-of-words vector: texts that share words are close."""
    out = [0.0] * dims
    for word in text.lower().split():
        h = int(hashlib.sha256(word.strip(".,?!").encode()).hexdigest(), 16)
        out[h % dims] += 1.0
    norm = math.sqrt(sum(v * v for v in out)) or 1.0
    return [v / norm for v in out]


class FakeVectors:
    """`PromptVectors` that embeds words; `offline` makes every call answer None."""

    model = "fake/embedding-v1"

    def __init__(self, *, offline: bool = False) -> None:
        self.offline = offline
        self.text_calls = 0

    async def of_texts(self, texts: Sequence[str]) -> VectorSet | None:
        self.text_calls += 1
        if self.offline:
            return None
        return VectorSet(self.model, [bag_vector(t) for t in texts])

    async def of_query(self, text: str) -> QueryVector | None:
        if self.offline or not text.strip():
            return None
        return QueryVector(self.model, bag_vector(text))


class MemIdeaFits:
    """Idea fits keyed by student and text digest."""

    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, str], Any] = {}

    async def get(self, student_id: UUID, text_digest: str) -> Any:
        return self.rows.get((student_id, text_digest))

    async def put(self, student_id: UUID, text_digest: str, fit: Any) -> None:
        self.rows[(student_id, text_digest)] = fit

"""Use case: hybrid search over shared passages the user may read (no leaks).

Passages are stored once per distinct text, so the same file added by several
students is one set of passages. The reader pre-filters by scope; this class makes
the decision: a passage is returned only if the user owns the notebook of the source
that holds it, or the source is a library item the library lets the user read, or a
lesson material of a lesson the user attends. Anything else, and any failure of a
check, drops the passage.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.notebooks.domain.enums import SourceKind
from app.modules.notebooks.ports.shared_passages import (
    SharedCandidate,
    SharedPassageReader,
)
from app.shared.actor import Actor
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.embeddings import EmbeddingIndex
from app.shared.contracts.library import LibrarySourceReader

OVERFETCH: Final = 4
"""Candidates asked per wanted passage: the access check drops some."""


@dataclass(frozen=True, slots=True)
class SharedPassage:
    """A readable passage and where the user may open it."""

    origin: str  # "notebook" | "library" | "lesson"
    source_id: UUID
    notebook_id: UUID
    ref_id: UUID  # notebook source id, library item id or lesson id
    title: str
    text: str


class SharedPassageSearch:
    """Finds passages by words and meaning among those the actor may read."""

    def __init__(
        self,
        *,
        reader: SharedPassageReader,
        library: LibrarySourceReader | None,
        schedule: ScheduleQueries | None,
        embeddings: EmbeddingIndex | None,
    ) -> None:
        """Store the collaborators; a missing one closes its kind of sources."""
        self.reader = reader
        self.library = library
        self.schedule = schedule
        self.embeddings = embeddings

    async def execute(
        self, actor: Actor, query: str, limit: int
    ) -> list[SharedPassage]:
        """Up to `limit` readable passages, best first, one per distinct text."""
        text = " ".join(query.split())
        if not text or limit <= 0:
            return []
        vector = await self.embeddings.embed_query(text) if self.embeddings else None
        candidates = await self.reader.search(
            actor.user_id, text, vector, limit * OVERFETCH
        )
        found: list[SharedPassage] = []
        seen: set[UUID] = set()
        allowed: dict[tuple[str, str], bool] = {}
        for c in candidates:
            if c.passage_id in seen:
                continue
            passage = await self._readable(actor, c, allowed)
            if passage is None:
                continue
            seen.add(c.passage_id)
            found.append(passage)
            if len(found) >= limit:
                break
        return found

    async def _readable(
        self, actor: Actor, c: SharedCandidate, memo: dict[tuple[str, str], bool]
    ) -> SharedPassage | None:
        """The passage as the actor may see it through this source, else None."""
        if c.owner_id == actor.user_id:
            return SharedPassage(
                "notebook",
                c.source_id,
                c.notebook_id,
                c.source_id,
                c.source_title,
                c.text,
            )
        if c.kind == SourceKind.LIBRARY_ITEM.value:
            item = _uuid(c.ref.get("item_id"))
            if item is not None and await self._cached(
                memo, ("library", str(item)), lambda: self._library_ok(actor, item)
            ):
                return SharedPassage(
                    "library", c.source_id, c.notebook_id, item, c.source_title, c.text
                )
        elif c.kind == SourceKind.LESSON_RESOURCE.value:
            lesson = _uuid(c.ref.get("lesson_id"))
            if lesson is not None and await self._cached(
                memo, ("lesson", str(lesson)), lambda: self._lesson_ok(actor, lesson)
            ):
                return SharedPassage(
                    "lesson", c.source_id, c.notebook_id, lesson, c.source_title, c.text
                )
        return None

    @staticmethod
    async def _cached(
        memo: dict[tuple[str, str], bool],
        key: tuple[str, str],
        check: Callable[[], Awaitable[bool]],
    ) -> bool:
        if key not in memo:
            memo[key] = await check()
        return memo[key]

    async def _library_ok(self, actor: Actor, item_id: UUID) -> bool:
        if self.library is None:
            return False
        try:
            await self.library.describe(item_id, actor)
        except Exception:  # unavailable, hidden, gone: all mean "not for this user"
            return False
        return True

    async def _lesson_ok(self, actor: Actor, lesson_id: UUID) -> bool:
        if self.schedule is None:
            return False
        try:
            return bool(await self.schedule.is_in_audience(actor.user_id, lesson_id))
        except Exception:
            return False


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None

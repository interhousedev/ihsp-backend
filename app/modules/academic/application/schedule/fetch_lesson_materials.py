"""The worker asks EMIS for the materials of one lesson (A3).

One timetable request for the lesson's week, through the requesting student's own EMIS
link, then the normal import restricted to this lesson. It adds and never purges: the
import skips known (lesson, url) pairs. EMIS's limiter and global pause apply.
"""

import datetime as dt
from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory, today
from app.modules.academic.domain.schedule.calendar import monday_of
from app.modules.academic.domain.schedule.term import Term, pick_current_term
from app.shared.clock import Clock
from app.shared.contracts.emis import (
    EmisAuthFailed,
    EmisClass,
    EmisSource,
    EmisUnavailable,
)
from app.shared.contracts.mcp_academic import (
    FetchReason,
    LessonFetchStore,
    MaterialFetch,
)

import structlog

log = structlog.get_logger(__name__)

_WEEK = dt.timedelta(days=6)


class LessonMaterialSync(Protocol):
    """The part of the timetable sync that imports one lesson's materials."""

    async def apply_lesson_materials(
        self,
        *,
        term: Term,
        group_id: UUID,
        user_id: UUID,
        classes: Sequence[EmisClass],
        window: tuple[dt.date, dt.date],
        lesson_id: UUID,
    ) -> int:
        """Add the materials; return how many are new."""
        ...


class FetchLessonMaterials:
    """Runs one fetch and always leaves its final state in the store."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        emis: EmisSource,
        sync: LessonMaterialSync,
        store: LessonFetchStore,
        clock: Clock,
    ) -> None:
        """Store the collaborators."""
        self._uow_factory = uow_factory
        self._emis = emis
        self._sync = sync
        self._store = store
        self._clock = clock

    async def execute(self, lesson_id: UUID, user_id: UUID, job_id: str) -> None:
        """Fetch and record the outcome; nothing here raises to the worker."""
        reason: FetchReason | None
        try:
            reason = await self._fetch(lesson_id, user_id)
        except EmisAuthFailed:
            reason = "emis_reauth"
        except EmisUnavailable:  # EmisPaused too: no waiting behind a global pause
            reason = "emis_busy"
        except Exception:  # noqa: BLE001 - a client is polling this state
            log.exception("lesson_materials_fetch_failed", lesson_id=str(lesson_id))
            reason = "emis_busy"
        await self.record(lesson_id, user_id, job_id, reason)

    async def record(
        self, lesson_id: UUID, user_id: UUID, job_id: str, reason: FetchReason | None
    ) -> None:
        """Store the outcome of a job."""
        failed = reason in ("emis_reauth", "emis_busy")
        await self._store.finish(
            lesson_id,
            user_id,
            MaterialFetch(
                job_id=job_id,
                status="failed" if failed else "done",
                started_at=self._clock.now(),
                reason=reason,
            ),
        )

    async def _fetch(self, lesson_id: UUID, user_id: UUID) -> FetchReason | None:
        day = today(self._clock)
        lesson, student, term = await self._load(lesson_id, user_id, day)
        if lesson is None or student is None:
            return None
        if term is None or not term.starts_on <= lesson.date <= term.ends_on:
            return "old_term"
        monday = monday_of(lesson.date)
        window = (max(monday, term.starts_on), min(monday + _WEEK, term.ends_on))
        classes = await self._emis.timetable(user_id, monday, monday + _WEEK)
        await self._sync.apply_lesson_materials(
            term=term,
            group_id=student.group_id,
            user_id=user_id,
            classes=classes,
            window=window,
            lesson_id=lesson_id,
        )
        return None

    async def _load(
        self, lesson_id: UUID, user_id: UUID, day: dt.date
    ) -> tuple[Any, Any, Term | None]:
        async with self._uow_factory() as uow:
            lesson = await uow.lessons.get(lesson_id)
            student = await uow.students.get(user_id)
            term = pick_current_term(await uow.terms.list_all(), day)
        return lesson, student, term

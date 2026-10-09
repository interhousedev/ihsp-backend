"""Weighted-token budget: a 5-hour session window and a Tashkent day (§ 3.6, NB-14).

Two pools: students' notebooks, and course workspaces, whose staff share one pool
with the author assistant (`ai:lms` keys). A call is always charged to the user who
makes it; the notebook decides the pool (`NotebookBudget.pool`).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Literal
from uuid import UUID

from app.modules.notebooks.domain.errors import LimitReachedError
from app.modules.notebooks.ports.budget_store import BudgetStore
from app.settings import Settings
from app.shared.clock import TASHKENT, Clock, local_today


@dataclass(frozen=True, slots=True)
class UsagePart:
    """Weighted tokens used against a limit, and when the counter resets."""

    used: int
    limit: int
    resets_at: datetime | None


@dataclass(frozen=True, slots=True)
class BudgetInfo:
    """The session and the day budget of a student."""

    session: UsagePart
    day: UsagePart


@dataclass(frozen=True, slots=True)
class LimitHit:
    """A limit that a request would exceed."""

    scope: Literal["session", "day"]
    resets_at: datetime


class NotebookBudget:
    """Counts weighted tokens per user and decides whether a call may be made."""

    def __init__(
        self,
        store: BudgetStore,
        clock: Clock,
        settings: Settings,
        *,
        for_course: bool = False,
        course: "NotebookBudget | None" = None,
    ) -> None:
        """Store the counters, the clock and the settings of this pool.

        `for_course` makes this the course staff pool (`lms_ai_*` limits) instead of
        the student pool. `course` is the pool of course workspaces (`pool(True)`);
        without it every notebook uses this pool.
        """
        self.store = store
        self.clock = clock
        self.settings = settings
        self.for_course = for_course
        self.course = course

    @property
    def session_limit(self) -> int:
        """Weighted tokens of one session window (read from the settings each time)."""
        limits = self.settings.limits
        if self.for_course:
            return limits.lms_ai_session_tokens
        return limits.nb_session_tokens_student

    @property
    def daily_limit(self) -> int:
        """Weighted tokens of one Tashkent day."""
        limits = self.settings.limits
        if self.for_course:
            return limits.lms_ai_daily_tokens
        return limits.nb_daily_tokens_student

    def pool(self, course: bool) -> "NotebookBudget":
        """The pool of a course workspace (`course=True`) or of a student notebook."""
        return self.course if course and self.course is not None else self

    def _next_midnight(self) -> datetime:
        tomorrow = local_today(self.clock) + timedelta(days=1)
        return datetime.combine(tomorrow, time.min, tzinfo=TASHKENT).astimezone(UTC)

    async def usage(self, user_id: UUID) -> BudgetInfo:
        """Return the session and day usage with their limits."""
        window = await self.store.session(user_id)
        active = window is not None and window.ends_at > self.clock.now()
        day_used = await self.store.day_used(user_id, local_today(self.clock))
        session = UsagePart(
            used=window.used if window is not None and active else 0,
            limit=self.session_limit,
            resets_at=window.ends_at if window is not None and active else None,
        )
        day = UsagePart(day_used, self.daily_limit, self._next_midnight())
        return BudgetInfo(session=session, day=day)

    async def check(self, user_id: UUID, estimate: int) -> LimitHit | None:
        """Return the limit a call of `estimate` weighted tokens would exceed."""
        info = await self.usage(user_id)
        hits: list[LimitHit] = []
        if info.session.used + estimate > info.session.limit:
            hits.append(LimitHit("session", self._session_reset(info)))
        if info.day.used + estimate > info.day.limit:
            hits.append(LimitHit("day", self._next_midnight()))
        return max(hits, key=lambda hit: hit.resets_at) if hits else None

    async def require(self, user_id: UUID, estimate: int) -> None:
        """Raise `LimitReachedError` (429, scope and reset time) when over a limit."""
        hit = await self.check(user_id, estimate)
        if hit is not None:
            raise LimitReachedError(
                params={"scope": hit.scope, "resets_at": hit.resets_at.isoformat()}
            )

    def _session_reset(self, info: BudgetInfo) -> datetime:
        if info.session.resets_at is not None:
            return info.session.resets_at
        return self.clock.now() + timedelta(hours=self.settings.limits.ai_session_hours)

    async def add(self, user_id: UUID, tokens: int) -> None:
        """Count the weighted tokens a call really used."""
        if tokens <= 0:
            return
        now = self.clock.now()
        window = await self.store.session(user_id)
        if window is None or window.ends_at <= now:
            hours = self.settings.limits.ai_session_hours
            await self.store.open_session(user_id, now + timedelta(hours=hours))
        await self.store.add_session(user_id, tokens)
        await self.store.add_day(user_id, local_today(self.clock), tokens)

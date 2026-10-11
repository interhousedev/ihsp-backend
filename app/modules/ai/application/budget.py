"""Token budgets and the smart tier's weekly requests (AI-8, AI-9, AI-13).

The session window (5 hours) and the Tashkent day count tokens; the smart tier
counts its requests per week (Monday 00:00 to Monday 00:00, Tashkent).

Two pools: the student and Administration assistants count in the `ai` store; the
course author assistant counts in the course staff pool (`ai:lms`), which the
course workspace of the notebooks module shares.
"""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from uuid import UUID

from app.modules.ai.application.assistant_profile import profile_for
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.ports.budget_store import BudgetStore
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.clock import TASHKENT, Clock, local_today
from app.shared.limits import LimitsProvider, StaticLimits


async def smart_weekly_limit(actor: Actor, limits: LimitsProvider) -> int | None:
    """The smart-tier requests this actor may send a week; None means no limit.

    The one place that decides the limit: the admin's value, the student's extension
    and the staff exemption all come from the limits provider. Staff are not limited,
    but their requests are still counted.
    """
    view = await limits.for_actor(actor)
    limit: int | None = view.ai_smart_requests_per_week_student
    return limit


@dataclass(frozen=True, slots=True)
class UsagePart:
    """Tokens used against a limit, and when the counter resets."""

    used: int
    limit: int | None  # None: unlimited
    resets_at: datetime | None


@dataclass(frozen=True, slots=True)
class SmartUsagePart:
    """Smart-tier requests of this week; limit and remaining are None when unlimited."""

    used: int
    limit: int | None
    remaining: int | None
    resets_at: datetime


@dataclass(frozen=True, slots=True)
class UsageInfo:
    """Remaining budget shown under the chat input."""

    session: UsagePart
    day: UsagePart
    smart: SmartUsagePart | None = None
    """Smart-tier requests of the week; None for an assistant without a smart tier."""


@dataclass(frozen=True, slots=True)
class LimitHit:
    """A limit that a request would exceed."""

    scope: Literal["session", "day"]
    resets_at: datetime
    pool: Literal["ai", "lms"] = "ai"

    def params(self) -> dict[str, str]:
        """Return the parameters of the `ai/limit-reached` error."""
        return {
            "scope": self.scope,
            "resets_at": self.resets_at.isoformat(),
            "pool": self.pool,
        }


@dataclass(frozen=True, slots=True)
class SmartLimitHit:
    """The smart tier's requests of this week are used up."""

    limit: int
    resets_at: datetime

    def params(self) -> dict[str, str]:
        """Return the parameters of the `ai/smart-weekly-limit` error."""
        return {
            "limit": str(self.limit),
            "date": self.resets_at.astimezone(TASHKENT).strftime("%d.%m.%Y"),
            "resets_at": self.resets_at.isoformat(),
        }


class BudgetService:
    """Counts tokens per user and pool and decides whether a request may be sent."""

    def __init__(
        self,
        store: BudgetStore,
        clock: Clock,
        settings: Settings,
        course_store: BudgetStore | None = None,
        limits: LimitsProvider | None = None,
    ) -> None:
        """Store the counters of both pools, the clock and the limits.

        Without `course_store` the course pool falls back to the main store (only
        in tests that do not use the course author assistant). The limits are read
        through `limits` (overrides, extensions, staff); without it the environment's.
        """
        self.store = store
        self.course_store = course_store or store
        self.clock = clock
        self.settings = settings
        self.limits = limits or StaticLimits(settings.limits)

    def _store(self, assistant: Assistant) -> BudgetStore:
        if profile_for(assistant, self.settings).course_pool:
            return self.course_store
        return self.store

    def _next_midnight(self) -> datetime:
        tomorrow = local_today(self.clock) + timedelta(days=1)
        return datetime.combine(tomorrow, time.min, tzinfo=TASHKENT).astimezone(UTC)

    def _week(self) -> tuple[date, datetime]:
        """The Monday of this week (Tashkent) and the moment the next week starts."""
        today = local_today(self.clock)
        monday = today - timedelta(days=today.weekday())
        next_monday = datetime.combine(
            monday + timedelta(days=7), time.min, tzinfo=TASHKENT
        )
        return monday, next_monday.astimezone(UTC)

    async def usage(self, user_id: UUID, assistant: Assistant) -> UsageInfo:
        """Return the session and day usage with their limits (no smart count)."""
        # Only the student assistant is limited for students; the other assistants
        # belong to staff, who have no quota (the pool is still counted).
        limits = await self.limits.for_user(
            user_id, unlimited=assistant is not Assistant.STUDENT
        )
        profile = profile_for(assistant, self.settings, limits=limits)
        store = self._store(assistant)
        window = await store.session(user_id)
        active = window is not None and window.ends_at > self.clock.now()
        day_used = await store.day_used(user_id, local_today(self.clock))
        session = UsagePart(
            used=window.used if window is not None and active else 0,
            limit=profile.session_tokens,
            resets_at=window.ends_at if window is not None and active else None,
        )
        day = UsagePart(day_used, profile.daily_tokens, self._next_midnight())
        return UsageInfo(session=session, day=day)

    async def smart_limit(self, actor: Actor) -> int | None:
        """The smart requests a week this actor may send (None: unlimited, staff)."""
        return await smart_weekly_limit(actor, self.limits)

    async def usage_for(self, actor: Actor, assistant: Assistant) -> UsageInfo:
        """Session, day and, for the student assistant, the smart requests of the week.

        The limit that applies to the actor decides the smart numbers.
        """
        info = await self.usage(actor.user_id, assistant)
        if assistant is not Assistant.STUDENT:
            return info
        limit = await self.smart_limit(actor)
        return replace(info, smart=await self.smart_usage(actor.user_id, limit))

    async def smart_usage(self, user_id: UUID, limit: int | None) -> SmartUsagePart:
        """The smart requests of this week against the limit the caller resolved."""
        monday, resets_at = self._week()
        used = await self.store.week_used(user_id, monday)
        remaining = None if limit is None else max(limit - used, 0)
        return SmartUsagePart(used, limit, remaining, resets_at)

    async def reserve_smart(
        self, user_id: UUID, limit: int | None
    ) -> SmartLimitHit | None:
        """Count one smart request of the week, refused when the limit is used up.

        The add is atomic in the store, so two messages sent at once cannot both take
        the last request. A refused request is given back at once. Without a limit
        (None) the request is counted and allowed.
        """
        monday, resets_at = self._week()
        total = await self.store.add_week(user_id, monday, 1, resets_at)
        if limit is None or total <= limit:
            return None
        await self.store.add_week(user_id, monday, -1, resets_at)
        return SmartLimitHit(limit, resets_at)

    async def release_smart(self, user_id: UUID) -> None:
        """Give back a smart request that was reserved but never sent."""
        monday, resets_at = self._week()
        await self.store.add_week(user_id, monday, -1, resets_at)

    async def check(
        self, user_id: UUID, assistant: Assistant, estimate: int
    ) -> LimitHit | None:
        """Return the limit a request of `estimate` tokens would exceed, if any."""
        info = await self.usage(user_id, assistant)
        pool: Literal["ai", "lms"] = (
            "lms" if profile_for(assistant, self.settings).course_pool else "ai"
        )
        hits: list[LimitHit] = []
        session_limit, day_limit = info.session.limit, info.day.limit
        if session_limit is not None and info.session.used + estimate > session_limit:
            hits.append(LimitHit("session", await self._session_reset(info), pool))
        if day_limit is not None and info.day.used + estimate > day_limit:
            hits.append(LimitHit("day", self._next_midnight(), pool))
        return max(hits, key=lambda hit: hit.resets_at) if hits else None

    async def _session_reset(self, info: UsageInfo) -> datetime:
        if info.session.resets_at is not None:
            return info.session.resets_at
        hours = (await self.limits.current()).ai_session_hours
        return self.clock.now() + timedelta(hours=hours)

    async def add(
        self, user_id: UUID, tokens: int, assistant: Assistant = Assistant.STUDENT
    ) -> None:
        """Count the tokens a model request used (input plus output) in the pool.

        The student and Administration assistants share the main store; the
        course author assistant counts in the course staff pool.
        """
        if tokens <= 0:
            return
        store = self._store(assistant)
        now = self.clock.now()
        window = await store.session(user_id)
        if window is None or window.ends_at <= now:
            hours = (await self.limits.current()).ai_session_hours
            await store.open_session(user_id, now + timedelta(hours=hours))
        await store.add_session(user_id, tokens)
        await store.add_day(user_id, local_today(self.clock), tokens)

"""Token budgets: a 5-hour session window and a Tashkent day (AI-8, AI-9)."""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Literal
from uuid import UUID

from app.modules.ai.application.assistant_profile import profile_for
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.ports.budget_store import BudgetStore
from app.settings import Settings
from app.shared.clock import TASHKENT, Clock, local_today


@dataclass(frozen=True, slots=True)
class UsagePart:
    """Tokens used against a limit, and when the counter resets."""

    used: int
    limit: int
    resets_at: datetime | None


@dataclass(frozen=True, slots=True)
class UsageInfo:
    """Remaining budget shown under the chat input."""

    session: UsagePart
    day: UsagePart


@dataclass(frozen=True, slots=True)
class LimitHit:
    """A limit that a request would exceed."""

    scope: Literal["session", "day"]
    resets_at: datetime


class BudgetService:
    """Counts tokens per user and decides whether a request may be sent."""

    def __init__(self, store: BudgetStore, clock: Clock, settings: Settings) -> None:
        """Store the counters, the clock and the limits."""
        self.store = store
        self.clock = clock
        self.settings = settings

    def _next_midnight(self) -> datetime:
        tomorrow = local_today(self.clock) + timedelta(days=1)
        return datetime.combine(tomorrow, time.min, tzinfo=TASHKENT).astimezone(UTC)

    async def usage(self, user_id: UUID, assistant: Assistant) -> UsageInfo:
        """Return the session and day usage with their limits."""
        profile = profile_for(assistant, self.settings)
        window = await self.store.session(user_id)
        active = window is not None and window.ends_at > self.clock.now()
        day_used = await self.store.day_used(user_id, local_today(self.clock))
        session = UsagePart(
            used=window.used if window is not None and active else 0,
            limit=profile.session_tokens,
            resets_at=window.ends_at if window is not None and active else None,
        )
        day = UsagePart(day_used, profile.daily_tokens, self._next_midnight())
        return UsageInfo(session=session, day=day)

    async def check(
        self, user_id: UUID, assistant: Assistant, estimate: int
    ) -> LimitHit | None:
        """Return the limit a request of `estimate` tokens would exceed, if any."""
        info = await self.usage(user_id, assistant)
        hits: list[LimitHit] = []
        if info.session.used + estimate > info.session.limit:
            hits.append(LimitHit("session", self._session_reset(info)))
        if info.day.used + estimate > info.day.limit:
            hits.append(LimitHit("day", self._next_midnight()))
        return max(hits, key=lambda hit: hit.resets_at) if hits else None

    def _session_reset(self, info: UsageInfo) -> datetime:
        if info.session.resets_at is not None:
            return info.session.resets_at
        return self.clock.now() + timedelta(hours=self.settings.limits.ai_session_hours)

    async def add(self, user_id: UUID, tokens: int) -> None:
        """Count the tokens a model request used (input plus output)."""
        if tokens <= 0:
            return
        now = self.clock.now()
        window = await self.store.session(user_id)
        if window is None or window.ends_at <= now:
            hours = self.settings.limits.ai_session_hours
            await self.store.open_session(user_id, now + timedelta(hours=hours))
        await self.store.add_session(user_id, tokens)
        await self.store.add_day(user_id, local_today(self.clock), tokens)

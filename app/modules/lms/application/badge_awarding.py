"""Backfilling a badge: awards in bounded, resumable, idempotent batches."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.modules.lms.domain.badge_model import Badge, BadgeScope
from app.modules.lms.domain.badges import (
    BadgeEvent,
    Occurrence,
    earned,
    holds,
    parse_rule,
)
from app.modules.lms.ports.badge_repository import (
    AwardStore,
    BackfillQueue,
    BadgeStore,
    EnrolmentFacts,
    PlatformFactsReader,
)


@dataclass(frozen=True, slots=True)
class BackfillResult:
    """One batch: where the next one starts and how many awards it wrote."""

    next_cursor: int | None
    awarded: int


def platform_earned_at(badge: Badge, facts: Any, now: datetime) -> bool:  # noqa: ANN401
    """Return True when the platform facts meet the badge's rule."""
    return platform_rule_met(badge.rule, facts, now)


def platform_rule_met(
    raw: dict[str, Any], facts: Any, now: datetime
) -> bool:  # noqa: ANN401
    """Return True when the platform facts meet a platform rule."""
    rule = parse_rule(raw)
    count = {
        BadgeEvent.LEVEL_REACHED: facts.level,
        BadgeEvent.COACH_RESOLVED: facts.coach_resolved,
        BadgeEvent.COURSES_COMPLETED: facts.courses_completed,
    }.get(rule.event, 0)
    if not count:
        return False
    event = Occurrence(rule.event, now, count=count)
    return holds(rule.condition, event, now)


class BackfillBadge:
    """Award a badge to everyone who already meets its rule."""

    def __init__(
        self,
        repo: BadgeStore,
        facts_reader: EnrolmentFacts,
        awards: AwardStore,
        queue: BackfillQueue,
        batch: int = 500,
        platform_facts: PlatformFactsReader | None = None,
    ) -> None:
        """Store the ports."""
        self.repo, self.reader, self.awards = repo, facts_reader, awards
        self.queue, self.batch, self.platform = queue, batch, platform_facts

    async def execute(
        self, badge_id: UUID, cursor: int | None = None
    ) -> BackfillResult:
        """Run one batch and queue the next one when rows remain."""
        badge = await self.repo.get(badge_id)
        if badge is None or not badge.enabled:
            return BackfillResult(None, 0)
        if badge.scope is BadgeScope.PLATFORM and self.platform is None:
            return BackfillResult(None, 0)
        nxt, awarded = await self._batch(badge, cursor)
        if nxt is not None:
            await self.queue.enqueue(badge.id, nxt)
        return BackfillResult(nxt, awarded)

    async def _batch(self, badge: Badge, cursor: int | None) -> tuple[int | None, int]:
        """Award one page of candidates; return the next cursor and the count."""
        awarded = 0
        if badge.scope is BadgeScope.PLATFORM:
            assert self.platform is not None
            now = datetime.now(UTC)
            rows, nxt = await self.platform.page(cursor, self.batch)
            for user_id, facts in rows:
                if platform_earned_at(badge, facts, now):
                    awarded += await self._award(badge, user_id, now)
            return nxt, awarded
        assert badge.course_id is not None
        rule = parse_rule(badge.rule)
        crows, nxt = await self.reader.page(badge.course_id, cursor, self.batch)
        for user_id, facts in crows:
            at = earned({badge.id: rule}, facts).get(badge.id)
            if at is not None:
                awarded += await self._award(badge, user_id, at)
        return nxt, awarded

    async def _award(self, badge: Badge, user_id: UUID, at: datetime) -> int:
        event = {
            "user_id": str(user_id),
            "badge_id": str(badge.id),
            "course_id": str(badge.course_id) if badge.course_id else None,
        }
        return int(await self.awards.award(badge.id, user_id, at, event))

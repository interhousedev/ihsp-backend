"""In-memory essay invite and feedback repositories and a clock-aware limiter."""

from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.admission.application.essay_invites import EssayInviteService
from app.modules.admission.application.essays import EssayService
from app.modules.admission.domain.essay_invites import EssayInvite, Feedback
from app.shared.base_error import RateLimitedError
from tests.admission.unit.fakes import NOW
from tests.admission.unit.test_essays import MemEssays
from tests.admission.unit.test_items_service import ItemsUow, World
from tests.fakes.clock import FixedClock


class MemInvites:
    """An EssayInviteRepository over a dict."""

    def __init__(self) -> None:
        self.rows: dict[UUID, EssayInvite] = {}

    async def add(self, invite: EssayInvite) -> EssayInvite:
        self.rows[invite.id] = invite
        return invite

    async def get(self, invite_id: UUID) -> EssayInvite | None:
        return self.rows.get(invite_id)

    async def by_token_hash(self, digest: str) -> EssayInvite | None:
        return next((i for i in self.rows.values() if i.token_hash == digest), None)

    async def list_for_essay(self, essay_id: UUID) -> list[EssayInvite]:
        rows = [i for i in self.rows.values() if i.essay_id == essay_id]
        return sorted(rows, key=lambda i: i.created_at or NOW, reverse=True)

    async def count_active(self, essay_id: UUID, now: datetime) -> int:
        rows = await self.list_for_essay(essay_id)
        return sum(1 for i in rows if i.is_active(now))

    async def revoke(self, invite_id: UUID, now: datetime) -> None:
        row = self.rows.get(invite_id)
        if row is not None and row.revoked_at is None:
            self.rows[invite_id] = replace(row, revoked_at=now)

    async def touch(self, invite_id: UUID, now: datetime) -> None:
        row = self.rows.get(invite_id)
        if row is not None:
            self.rows[invite_id] = replace(row, last_opened_at=now)


class MemFeedback:
    """An EssayFeedbackRepository over a dict; delete cascades to replies."""

    def __init__(self) -> None:
        self.rows: dict[UUID, Feedback] = {}

    async def add(self, item: Feedback) -> Feedback:
        self.rows[item.id] = item
        return item

    async def get(self, feedback_id: UUID) -> Feedback | None:
        return self.rows.get(feedback_id)

    async def list_for_essay(self, essay_id: UUID) -> list[Feedback]:
        rows = [f for f in self.rows.values() if f.essay_id == essay_id]
        return sorted(rows, key=lambda f: f.created_at)

    async def list_for_invite(self, invite_id: UUID) -> list[Feedback]:
        rows = [f for f in self.rows.values() if f.invite_id == invite_id]
        return sorted(rows, key=lambda f: f.created_at)

    async def set_resolved(self, feedback_id: UUID, at: datetime | None) -> None:
        row = self.rows.get(feedback_id)
        if row is not None:
            self.rows[feedback_id] = replace(row, resolved_at=at)

    async def delete(self, feedback_id: UUID) -> None:
        self.rows.pop(feedback_id, None)
        for child in [f.id for f in self.rows.values() if f.parent_id == feedback_id]:
            await self.delete(child)


class WindowLimiter:
    """A fixed-window RateLimiter driven by a FixedClock."""

    def __init__(self, clock: FixedClock) -> None:
        self._clock = clock
        self.hits: dict[str, list[datetime]] = {}

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> int:
        now = self._clock.now()
        recent = [
            t
            for t in self.hits.get(key, [])
            if (now - t).total_seconds() < window_seconds
        ]
        if len(recent) >= limit:
            raise RateLimitedError(params={"retry_after": window_seconds})
        recent.append(now)
        self.hits[key] = recent
        return len(recent)


class InvitesUow(ItemsUow):
    """ItemsUow with essays, invites and feedback."""

    def __init__(self, desk: "InviteDesk") -> None:
        super().__init__(desk.w.store, desk.w.data)
        self.essays = desk.essays
        self.essay_invites = desk.invites
        self.essay_feedback = desk.feedback


class InviteDesk:
    """A student world with the essay and invite services."""

    def __init__(self) -> None:
        self.w = World()
        self.essays = MemEssays()
        self.invites = MemInvites()
        self.feedback = MemFeedback()
        self.clock = FixedClock(NOW)
        self.limiter = WindowLimiter(self.clock)

        def uow() -> Any:
            return InvitesUow(self)

        self.essay_svc = EssayService(uow, self.w.policy, self.clock)
        self.svc = EssayInviteService(uow, self.w.policy, self.clock, self.limiter)

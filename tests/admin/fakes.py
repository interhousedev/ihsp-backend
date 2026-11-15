"""In-memory broadcast repository, delivery reader and unit of work."""

import asyncio
import copy
from collections.abc import Collection
from datetime import datetime
from types import TracebackType
from typing import Self
from uuid import UUID

from app.modules.admin.domain.broadcast import Broadcast, BroadcastStatus
from app.modules.admin.domain.errors import BotNotFoundError, BroadcastNotFoundError
from app.modules.admin.domain.telegram_bot import TelegramBot
from app.modules.admin.ports.delivery_reader import DeliveryCounts
from app.shared.notifications import AuditDraft, NotificationDraft


class InMemoryBroadcastRepository:
    """Implements BroadcastRepository with copies, like a database would."""

    def __init__(self) -> None:
        """Start empty."""
        self.rows: dict[UUID, Broadcast] = {}

    async def add(self, broadcast: Broadcast) -> None:
        """Store a copy."""
        self.rows[broadcast.id] = copy.deepcopy(broadcast)

    async def get(self, broadcast_id: UUID, *, for_update: bool = False) -> Broadcast:
        """Return a copy or raise BroadcastNotFoundError."""
        if broadcast_id not in self.rows:
            raise BroadcastNotFoundError(support_details=str(broadcast_id))
        return copy.deepcopy(self.rows[broadcast_id])

    async def save(self, broadcast: Broadcast) -> None:
        """Replace the stored copy."""
        self.rows[broadcast.id] = copy.deepcopy(broadcast)

    async def list_page(
        self,
        *,
        status: BroadcastStatus | None,
        before: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Broadcast]:
        """Return broadcasts newest first."""
        rows = sorted(
            self.rows.values(), key=lambda b: (b.created_at, str(b.id)), reverse=True
        )
        if status is not None:
            rows = [b for b in rows if b.status == status]
        if before is not None:
            key = (before[0], str(before[1]))
            rows = [b for b in rows if (b.created_at, str(b.id)) < key]
        return [copy.deepcopy(b) for b in rows[:limit]]

    async def claim_scheduled(self, now: datetime) -> list[Broadcast]:
        """Return scheduled broadcasts that are due."""
        due = [
            b
            for b in self.rows.values()
            if b.status == BroadcastStatus.SCHEDULED
            and b.scheduled_at is not None
            and b.scheduled_at <= now
        ]
        return [copy.deepcopy(b) for b in due]

    async def list_sending(self) -> list[Broadcast]:
        """Return broadcasts being delivered."""
        return [
            copy.deepcopy(b)
            for b in self.rows.values()
            if b.status == BroadcastStatus.SENDING
        ]


class InMemoryBotRepository:
    """Implements BotRepository; ``links`` maps bot id to linked user ids."""

    def __init__(self) -> None:
        """Start empty."""
        self.rows: dict[UUID, TelegramBot] = {}
        self.links: dict[UUID, set[UUID]] = {}
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._held: dict[asyncio.Task[object], set[UUID]] = {}

    async def list_all(self) -> list[TelegramBot]:
        """Default first, then by creation."""
        rows = sorted(
            self.rows.values(), key=lambda b: (not b.is_default, b.created_at)
        )
        return [copy.deepcopy(b) for b in rows]

    async def get(self, bot_id: UUID, *, for_update: bool = False) -> TelegramBot:
        """A copy or BotNotFoundError; ``for_update`` locks the row like FOR UPDATE.

        The lock is held by the current task until its unit of work exits.
        """
        if bot_id not in self.rows:
            raise BotNotFoundError(support_details=str(bot_id))
        task = asyncio.current_task()
        if for_update and task is not None:
            held = self._held.setdefault(task, set())
            if bot_id not in held:
                await self._locks.setdefault(bot_id, asyncio.Lock()).acquire()
                held.add(bot_id)
        return copy.deepcopy(self.rows[bot_id])

    def release_locks(self) -> None:
        """Release the row locks of the current task (end of its transaction)."""
        task = asyncio.current_task()
        for bot_id in self._held.pop(task, set()) if task else set():
            self._locks[bot_id].release()

    async def by_telegram_id(self, telegram_id: int) -> TelegramBot | None:
        """Find by Telegram id."""
        found = [b for b in self.rows.values() if b.telegram_id == telegram_id]
        return copy.deepcopy(found[0]) if found else None

    async def add(self, bot: TelegramBot, *, actor_id: UUID | None) -> None:
        """Store a copy."""
        self.rows[bot.id] = copy.deepcopy(bot)

    async def save(self, bot: TelegramBot, *, actor_id: UUID | None) -> None:
        """Replace the stored copy."""
        self.rows[bot.id] = copy.deepcopy(bot)

    async def members(self, bot_id: UUID, user_ids: Collection[UUID]) -> set[UUID]:
        """The given users linked to the bot."""
        return self.links.get(bot_id, set()) & set(user_ids)

    async def member_counts(self) -> dict[UUID, int]:
        """Linked users per bot."""
        return {bot_id: len(users) for bot_id, users in self.links.items()}


class FakeDeliveryReader:
    """Delivery counts that a test sets by hand."""

    def __init__(self) -> None:
        """Start with zero counts for every broadcast."""
        self.by_broadcast: dict[UUID, DeliveryCounts] = {}

    def set(
        self,
        broadcast_id: UUID,
        *,
        total: int,
        sent: int = 0,
        failed: int = 0,
        blocked: int = 0,
        open: int = 0,  # noqa: A002 - mirrors the DeliveryCounts field
    ) -> None:
        """Set the counts the reader reports."""
        self.by_broadcast[broadcast_id] = DeliveryCounts(
            total=total, sent=sent, failed=failed, blocked=blocked, open=open
        )

    async def counts(self, broadcast_id: UUID) -> DeliveryCounts:
        """Return the counts set by the test."""
        return self.by_broadcast.get(broadcast_id, DeliveryCounts(0, 0, 0, 0, 0))


class AdminWorld:
    """State shared by the units of work of one test."""

    def __init__(self) -> None:
        """Start empty."""
        self.broadcasts = InMemoryBroadcastRepository()
        self.deliveries = FakeDeliveryReader()
        self.bots = InMemoryBotRepository()
        self.outbox: list[NotificationDraft] = []
        self.audits: list[AuditDraft] = []
        self.batches: list[int] = []
        """Number of notification drafts of every commit that had any."""

    def uow(self) -> "FakeAdminUnitOfWork":
        """Build a unit of work over the shared state (use as the factory)."""
        return FakeAdminUnitOfWork(self)


class FakeAdminUnitOfWork:
    """Implements AdminUnitOfWork; drafts reach the world on commit only."""

    def __init__(self, world: AdminWorld) -> None:
        """Share the world between units of work."""
        self._world = world
        self._outbox: list[NotificationDraft] = []
        self._audit: list[AuditDraft] = []

    @property
    def broadcasts(self) -> InMemoryBroadcastRepository:
        """The shared repository."""
        return self._world.broadcasts

    @property
    def bots(self) -> InMemoryBotRepository:
        """The shared bot registry."""
        return self._world.bots

    @property
    def deliveries(self) -> FakeDeliveryReader:
        """The shared reader."""
        return self._world.deliveries

    async def __aenter__(self) -> Self:
        """Open (nothing to do)."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close: row locks end with the transaction."""
        self._world.bots.release_locks()

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue drafts."""
        self._outbox.extend(drafts)

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events."""
        self._audit.extend(drafts)

    async def commit(self) -> None:
        """Hand queued drafts to the world."""
        if self._outbox:
            self._world.batches.append(len(self._outbox))
        self._world.outbox.extend(self._outbox)
        self._world.audits.extend(self._audit)
        self._outbox, self._audit = [], []

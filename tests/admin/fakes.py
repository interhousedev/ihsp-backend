"""In-memory broadcast repository, delivery reader and unit of work."""

import copy
from datetime import datetime
from types import TracebackType
from typing import Self
from uuid import UUID

from app.modules.admin.domain.broadcast import Broadcast, BroadcastStatus
from app.modules.admin.domain.errors import BroadcastNotFoundError
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
        """Close (nothing to do)."""

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

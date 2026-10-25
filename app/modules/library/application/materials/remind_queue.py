"""Remind librarians that materials wait for review longer than the service level."""

from app.modules.library.domain.moderation_rules import is_overdue
from app.modules.library.ports.unit_of_work import UowFactory
from app.settings import LibrarySettings
from app.shared.actor import Role
from app.shared.clock import Clock, local_today
from app.shared.contracts.identity import IdentityDirectory
from app.shared.notifications import NotificationDraft, NotificationType

SECONDS_PER_HOUR = 3600


class RemindQueue:
    """Daily: one reminder per librarian when items waited over the SLA."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        identity: IdentityDirectory,
        settings: LibrarySettings,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.identity = identity
        self.settings = settings

    async def execute(self) -> int:
        """Queue the reminders; return how many were queued (0 when all is fresh)."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            waiting = await uow.moderation.pending_times()
            late = [
                entry.at
                for entry in waiting
                if is_overdue(entry.at, now, self.settings.queue_sla_school_days)
            ]
            if not late:
                return 0
            hours = round((now - min(late)).total_seconds() / SECONDS_PER_HOUR)
            day = local_today(self.clock).isoformat()
            recipients = await self.identity.user_ids_with_roles(
                [Role.LIBRARIAN, Role.ADMIN]
            )
            drafts = [
                NotificationDraft(
                    user_id=user_id,
                    type=NotificationType.LIBRARY_QUEUE_WAITING,
                    payload={"count": len(late), "oldest_hours": hours},
                    dedupe_key=f"library_queue_waiting:{user_id}:{day}",
                )
                for user_id in recipients
            ]
            if drafts:
                uow.notify(*drafts)
                await uow.commit()
        return len(drafts)

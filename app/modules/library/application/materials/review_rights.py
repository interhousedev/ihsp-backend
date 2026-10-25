"""Tell librarians about book permissions that end within 60 days (LIB-3)."""

from app.modules.library.domain.moderation_rules import permission_ends_soon
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Role
from app.shared.clock import Clock, local_today
from app.shared.contracts.identity import IdentityDirectory
from app.shared.notifications import NotificationDraft, NotificationType


class ReviewRights:
    """Daily: one message per librarian when a book's permission ends soon."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, identity: IdentityDirectory
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.identity = identity

    async def execute(self) -> int:
        """Queue the messages; return how many were queued."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            ids = await uow.moderation.rights_candidates()
            books = await uow.items.get_many(ids)
            ending = [
                item
                for item in books.values()
                if item.book is not None and permission_ends_soon(item.book, now)
            ]
            if not ending:
                return 0
            day = local_today(self.clock).isoformat()
            recipients = await self.identity.user_ids_with_roles(
                [Role.LIBRARIAN, Role.ADMIN]
            )
            drafts = [
                NotificationDraft(
                    user_id=user_id,
                    type=NotificationType.LIBRARY_QUEUE_WAITING,
                    payload={"count": len(ending), "oldest_hours": 0, "kind": "rights"},
                    dedupe_key=f"library_queue_waiting:{user_id}:rights:{day}",
                )
                for user_id in recipients
            ]
            if drafts:
                uow.notify(*drafts)
                await uow.commit()
        return len(drafts)

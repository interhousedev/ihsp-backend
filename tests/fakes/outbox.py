"""In-memory outbox and audit writers that collect drafts."""

from app.shared.notifications import AuditDraft, NotificationDraft

from sqlalchemy.ext.asyncio import AsyncSession


class InMemoryOutbox:
    """Implements OutboxWriter (write_notifications) and AuditWriter (write_audit)."""

    def __init__(self) -> None:
        """Start empty."""
        self.notifications: list[NotificationDraft] = []
        self.audits: list[AuditDraft] = []
        self.claimed: set[str] = set()  # dedupe keys a dispatcher already took

    async def write_notifications(
        self, session: AsyncSession, drafts: list[NotificationDraft]
    ) -> None:
        """Collect notification drafts."""
        self.notifications.extend(drafts)

    async def write_audit(
        self, session: AsyncSession, drafts: list[AuditDraft]
    ) -> None:
        """Collect audit drafts."""
        self.audits.extend(drafts)

    async def cancel_pending(self, session: AsyncSession, dedupe_key: str) -> bool:
        """Drop an unclaimed draft; False when it is claimed or unknown."""
        if dedupe_key in self.claimed:
            return False
        kept = [d for d in self.notifications if d.dedupe_key != dedupe_key]
        found = len(kept) != len(self.notifications)
        self.notifications = kept
        return found

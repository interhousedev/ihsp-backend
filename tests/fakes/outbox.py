"""In-memory outbox and audit writers that collect drafts."""

from app.shared.notifications import AuditDraft, NotificationDraft

from sqlalchemy.ext.asyncio import AsyncSession


class InMemoryOutbox:
    """Implements OutboxWriter (write_notifications) and AuditWriter (write_audit)."""

    def __init__(self) -> None:
        """Start empty."""
        self.notifications: list[NotificationDraft] = []
        self.audits: list[AuditDraft] = []

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

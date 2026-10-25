"""No-op outbox and audit writers for module tests until I1 wires the real ones."""

from app.shared.notifications import AuditDraft, NotificationDraft

from sqlalchemy.ext.asyncio import AsyncSession


async def noop_outbox_writer(
    session: AsyncSession, drafts: list[NotificationDraft]
) -> None:
    """Accept notification drafts and write nothing."""


async def noop_audit_writer(session: AsyncSession, drafts: list[AuditDraft]) -> None:
    """Accept audit drafts and write nothing."""

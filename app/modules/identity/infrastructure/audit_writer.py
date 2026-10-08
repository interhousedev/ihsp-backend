"""AuditWriter: inserts queued audit drafts in the use case's transaction."""

import ipaddress

from app.modules.identity.infrastructure.orm import AuditEvent
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft

from sqlalchemy.ext.asyncio import AsyncSession


def _valid_ip(value: str | None) -> str | None:
    """An unparseable address must never fail a business transaction."""
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


async def write_audit_events(session: AsyncSession, drafts: list[AuditDraft]) -> None:
    """Insert one id.audit_events row per draft."""
    session.add_all(
        AuditEvent(
            id=new_id(),
            user_id=draft.user_id,
            actor_id=draft.actor_id,
            type=draft.type,
            ip=_valid_ip(draft.ip),
            user_agent=draft.user_agent,
            meta=draft.metadata or {},
        )
        for draft in drafts
    )
    await session.flush()

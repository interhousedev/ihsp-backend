"""Small helper to build audit drafts with the request's IP and device."""

from typing import Any
from uuid import UUID

from app.modules.identity.application.request_context import RequestContext
from app.shared.notifications import AuditDraft


def make_audit(
    event_type: str,
    *,
    user_id: UUID | None,
    ctx: RequestContext | None = None,
    actor_id: UUID | None = None,
    **metadata: Any,
) -> AuditDraft:
    """Return an AuditDraft; actor_id is set only when someone else acted."""
    ctx = ctx or RequestContext()
    return AuditDraft(
        type=event_type,
        user_id=user_id,
        actor_id=actor_id if actor_id != user_id else None,
        ip=ctx.valid_ip,
        user_agent=ctx.device or None,
        metadata=metadata or None,
    )

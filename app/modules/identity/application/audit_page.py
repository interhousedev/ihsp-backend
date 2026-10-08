"""An audit page with the people named as actors."""

from dataclasses import dataclass, field
from uuid import UUID

from app.modules.identity.domain.audit_event import AuditEventRecord
from app.modules.identity.domain.user import User
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort
from app.shared.pagination import Page


@dataclass(frozen=True, slots=True)
class AuditPage:
    """Events plus the users behind ``actor_id``."""

    items: list[AuditEventRecord]
    actors: dict[UUID, User] = field(default_factory=dict)
    next_cursor: str | None = None


async def with_actors(
    uow: IdentityUnitOfWorkPort, page: Page[AuditEventRecord]
) -> AuditPage:
    """Attach the actors of the events."""
    actor_ids = list({e.actor_id for e in page.items if e.actor_id is not None})
    actors = await uow.users.get_many(actor_ids)
    return AuditPage(items=page.items, actors=actors, next_cursor=page.next_cursor)

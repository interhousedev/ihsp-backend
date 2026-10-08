"""List broadcasts for the admin platform (ADM-11)."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.modules.admin.application.broadcast_view import (
    BroadcastPageView,
    BroadcastPresenter,
)
from app.modules.admin.domain.broadcast import BroadcastStatus
from app.modules.admin.ports.unit_of_work import AdminUnitOfWork
from app.shared.actor import Actor, Role
from app.shared.base_error import ValidationFailedError
from app.shared.pagination import decode_cursor, encode_cursor


def _parse_cursor(cursor: str | None) -> tuple[datetime, UUID] | None:
    try:
        data = decode_cursor(cursor)
        if data is None:
            return None
        return datetime.fromisoformat(data["c"]), UUID(data["i"])
    except (ValueError, KeyError, TypeError):
        raise ValidationFailedError(support_details="invalid cursor") from None


class ListBroadcasts:
    """Returns a page of broadcasts, newest first."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AdminUnitOfWork],
        presenter: BroadcastPresenter,
    ) -> None:
        """Store the unit of work factory and the presenter."""
        self.uow_factory = uow_factory
        self.presenter = presenter

    async def execute(
        self,
        actor: Actor,
        *,
        status: BroadcastStatus | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> BroadcastPageView:
        """Load a page, optionally filtered by status."""
        actor.require(Role.ADMIN)
        before = _parse_cursor(cursor)
        async with self.uow_factory() as uow:
            rows = await uow.broadcasts.list_page(
                status=status, before=before, limit=limit + 1
            )
            page = rows[:limit]
            items = await self.presenter.present(uow, page)
        next_cursor = None
        if len(rows) > limit:
            last = page[-1]
            next_cursor = encode_cursor(
                {"c": last.created_at.isoformat(), "i": str(last.id)}
            )
        return BroadcastPageView(items=items, next_cursor=next_cursor)

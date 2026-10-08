"""List the web notification center (WEB-27, UF-WEB-15)."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.modules.notify.application.notification_view import (
    NotificationPageView,
    present,
    uses_staff_app,
)
from app.modules.notify.domain.notification_filter import NotificationFilter
from app.modules.notify.ports.unit_of_work import NotifyUnitOfWork
from app.settings import UrlsSettings
from app.shared.actor import Actor
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.i18n.core import I18nCore
from app.shared.pagination import decode_cursor, encode_cursor

DEFAULT_LOCALE = "ru"


def _parse_cursor(cursor: str | None) -> tuple[datetime, UUID] | None:
    try:
        data = decode_cursor(cursor)
        if data is None:
            return None
        return datetime.fromisoformat(data["c"]), UUID(data["i"])
    except (ValueError, KeyError, TypeError):
        raise ValidationFailedError(support_details="invalid cursor") from None


class ListNotifications:
    """Returns one page of the user's notifications, newest first."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], NotifyUnitOfWork],
        identity: IdentityDirectory,
        i18n: I18nCore,
        urls: UrlsSettings,
        clock: Clock,
    ) -> None:
        """Store the ports and the app URLs used for links."""
        self.uow_factory = uow_factory
        self.identity = identity
        self.i18n = i18n
        self.urls = urls
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        notification_filter: NotificationFilter = NotificationFilter.ALL,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> NotificationPageView:
        """Load a page; `announcements` are broadcasts, `activity` is the rest."""
        before = _parse_cursor(cursor)
        user = await self.identity.get_user(actor.user_id)
        locale = user.locale if user is not None else DEFAULT_LOCALE
        async with self.uow_factory() as uow:
            rows = await uow.notifications.list_for_user(
                actor.user_id,
                notification_filter,
                now=self.clock.now(),
                before=before,
                limit=limit + 1,
            )
        page, more = rows[:limit], len(rows) > limit
        staff = uses_staff_app(actor.roles)
        items = [
            present(row, locale=locale, staff=staff, i18n=self.i18n, urls=self.urls)
            for row in page
        ]
        next_cursor = None
        if more:
            last = page[-1]
            next_cursor = encode_cursor(
                {"c": last.created_at.isoformat(), "i": str(last.id)}
            )
        return NotificationPageView(items=items, next_cursor=next_cursor)

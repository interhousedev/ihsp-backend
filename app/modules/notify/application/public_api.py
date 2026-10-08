"""NotifyApi implementation for other modules and composition endpoints."""

from collections.abc import Callable
from dataclasses import asdict
from typing import Any
from uuid import UUID

from app.modules.notify.application.notification_view import present
from app.modules.notify.domain.notification_filter import NotificationFilter
from app.modules.notify.ports.unit_of_work import NotifyUnitOfWork
from app.settings import UrlsSettings
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.i18n.core import I18nCore

DEFAULT_LOCALE = "ru"


class NotifyApiImpl:
    """Unread count and latest announcements (implements NotifyApi)."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], NotifyUnitOfWork],
        identity: IdentityDirectory,
        i18n: I18nCore,
        urls: UrlsSettings,
        clock: Clock,
    ) -> None:
        """Store the ports used to read and describe notifications."""
        self.uow_factory = uow_factory
        self.identity = identity
        self.i18n = i18n
        self.urls = urls
        self.clock = clock

    async def unread_count(self, user_id: UUID) -> int:
        """Return the number of unread notifications."""
        async with self.uow_factory() as uow:
            return await uow.notifications.unread_count(user_id, now=self.clock.now())

    async def latest_announcements(
        self, user_id: UUID, limit: int = 3
    ) -> list[dict[str, Any]]:
        """Return the newest broadcasts as NotificationItem dicts."""
        user = await self.identity.get_user(user_id)
        locale = user.locale if user is not None else DEFAULT_LOCALE
        async with self.uow_factory() as uow:
            rows = await uow.notifications.list_for_user(
                user_id,
                NotificationFilter.ANNOUNCEMENTS,
                now=self.clock.now(),
                before=None,
                limit=limit,
            )
        views = [
            present(row, locale=locale, staff=False, i18n=self.i18n, urls=self.urls)
            for row in rows
        ]
        return [asdict(view) for view in views]

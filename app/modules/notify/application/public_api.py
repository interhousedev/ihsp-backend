"""NotifyApi implementation for other modules and composition endpoints."""

import datetime as dt
import hashlib
from collections.abc import Callable
from dataclasses import asdict
from typing import Any
from uuid import UUID

from app.modules.notify.application.notification_view import present
from app.modules.notify.domain.notification_filter import NotificationFilter
from app.modules.notify.ports.unit_of_work import NotifyUnitOfWork
from app.settings import UrlsSettings
from app.shared.actor import Role
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.i18n.core import I18nCore
from app.shared.notifications import NotificationDraft, NotificationType

DEFAULT_LOCALE = "ru"
KNOWLEDGE_GAP_QUERY_LIMIT = 300
KNOWLEDGE_GAP_DEDUPE = dt.timedelta(hours=24)


def normalize_query(query: str) -> str:
    """Lowercase and collapse whitespace, the identity of a query for dedupe."""
    return " ".join(query.lower().split())


class NotifyApiImpl:
    """Unread count, announcements and knowledge-gap alerts."""

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

    async def notify_knowledge_gap(
        self,
        *,
        query: str,
        chat_kind: str,
        user_role: str,
        audience: str = "staff",
        chat_id: str | None = None,
        notebook_id: str | None = None,
    ) -> int:
        """Notify all administrators; skip a query announced in the last 24 hours."""
        normalized = normalize_query(query)
        if not normalized:
            return 0
        digest = hashlib.sha256(normalized.encode()).hexdigest()[:32]
        now = self.clock.now()
        prefix = f"knowledge-gap:{digest}:"
        admins = await self.identity.user_ids_with_roles([Role.ADMIN])
        if not admins:
            return 0
        async with self.uow_factory() as uow:
            if await uow.notifications.dedupe_key_seen_since(
                prefix, now - KNOWLEDGE_GAP_DEDUPE
            ):
                return 0
            payload = {
                "query": " ".join(query.split())[:KNOWLEDGE_GAP_QUERY_LIMIT],
                "chat_kind": chat_kind,
                "chat_id": chat_id,
                "notebook_id": notebook_id,
                "user_role": user_role,
                "audience": audience,
            }
            stamp = int(now.timestamp())
            uow.notify(
                *(
                    NotificationDraft(
                        user_id=admin,
                        type=NotificationType.KNOWLEDGE_GAP,
                        payload=payload,
                        dedupe_key=f"{prefix}{admin}:{stamp}",
                    )
                    for admin in admins
                )
            )
            await uow.commit()
        return len(admins)

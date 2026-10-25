"""What the notification center returns for one notification."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.notify.application.describe import describe
from app.modules.notify.domain.notification import Notification
from app.settings import UrlsSettings
from app.shared.actor import Role
from app.shared.i18n.core import I18nCore


@dataclass(frozen=True, slots=True)
class NotificationView:
    """A notification described in the reader's language."""

    id: UUID
    type: str
    title: str
    body: str
    link: str | None
    created_at: datetime
    read_at: datetime | None


@dataclass(frozen=True, slots=True)
class NotificationPageView:
    """A page of notifications and the cursor of the next page."""

    items: list[NotificationView]
    next_cursor: str | None


def uses_staff_app(roles: frozenset[Role]) -> bool:
    """Teachers who are not students get links into the staff portal."""
    return Role.TEACHER in roles and Role.STUDENT not in roles


def present(
    notification: Notification,
    *,
    locale: str,
    staff: bool,
    i18n: I18nCore,
    urls: UrlsSettings,
) -> NotificationView:
    """Describe one notification for the web."""
    description = describe(
        notification.type,
        notification.payload,
        locale,
        i18n=i18n,
        urls=urls,
        staff=staff,
    )
    return NotificationView(
        id=notification.id,
        type=str(notification.type),
        title=description.title,
        body=description.body,
        link=description.link,
        created_at=notification.created_at,
        read_at=notification.read_at,
    )

"""The push payload of a notification, built from its web description."""

from app.modules.notify.application.describe import describe
from app.modules.notify.application.format import strip_html
from app.modules.notify.application.notification_view import uses_staff_app
from app.modules.notify.domain.notification import Notification
from app.modules.notify.domain.push_payload import PushPayload
from app.settings import UrlsSettings
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nCore

NOTIFICATIONS_PATH = "/notifications/"


def _absolute(link: str | None, base: str) -> str:
    """Make the link absolute; notifications without one open the notification list."""
    if not link:
        return f"{base}{NOTIFICATIONS_PATH}"
    if link.startswith("/"):
        return f"{base}{link}"
    return link


def build_push_payload(
    notification: Notification,
    user: UserRef,
    *,
    i18n: I18nCore,
    urls: UrlsSettings,
) -> PushPayload:
    """Describe the notification in the user's language as plain text with a full URL.

    `tag` is the notification id, so a push that arrives twice (after a crash between
    sending and saving) replaces itself in the browser instead of showing twice.
    """
    staff = uses_staff_app(user.roles)
    description = describe(
        notification.type,
        notification.payload,
        user.locale,
        i18n=i18n,
        urls=urls,
        staff=staff,
    )
    base = (urls.staff if staff else urls.sp).rstrip("/")
    return PushPayload(
        title=strip_html(description.title),
        body=strip_html(description.body),
        url=_absolute(description.link, base),
        tag=str(notification.id),
        notification_id=str(notification.id),
        type=notification.type.value,
    )

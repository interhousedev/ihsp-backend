"""Message about an email that was not delivered."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class MailBouncedRenderer(DescribedRenderer):
    """Message about an email that was not delivered."""

    notification_type = NotificationType.MAIL_BOUNCED

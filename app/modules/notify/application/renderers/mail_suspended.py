"""Notice that the mailbox was suspended."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class MailSuspendedRenderer(DescribedRenderer):
    """Notice that the mailbox was suspended."""

    notification_type = NotificationType.MAIL_SUSPENDED

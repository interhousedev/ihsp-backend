"""A new line in the thread of an excuse."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class ExcuseMessageRenderer(DescribedRenderer):
    """A new line in the thread of an excuse."""

    notification_type = NotificationType.EXCUSE_MESSAGE

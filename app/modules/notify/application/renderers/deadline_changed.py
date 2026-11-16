"""Telegram notice: deadline changed."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class DeadlineChangedRenderer(DescribedRenderer):
    """Title, body and a button to the admission app."""

    notification_type = NotificationType.DEADLINE_CHANGED
    link_button_key = "notify-btn-open-deadlines"

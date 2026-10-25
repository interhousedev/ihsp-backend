"""Telegram reminder for librarians that materials wait for review."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class LibraryQueueWaitingRenderer(DescribedRenderer):
    """Reminder with the queue length and the oldest wait, plus a queue button."""

    notification_type = NotificationType.LIBRARY_QUEUE_WAITING
    link_button_key = "notify-btn-open-library-queue"

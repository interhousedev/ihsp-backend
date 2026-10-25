"""Telegram notice that a new reading list was published."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class LibraryReadingListNewRenderer(DescribedRenderer):
    """Tells students about a reading list, with a button to open it."""

    notification_type = NotificationType.LIBRARY_READING_LIST_NEW
    link_button_key = "notify-btn-open-library-list"

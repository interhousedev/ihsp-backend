"""Telegram notice that an item was taken down."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class LibraryItemUnpublishedRenderer(DescribedRenderer):
    """Tells the owner of an unpublished or taken-down item why, with a button."""

    notification_type = NotificationType.LIBRARY_ITEM_UNPUBLISHED
    link_button_key = "notify-btn-open-library-item"

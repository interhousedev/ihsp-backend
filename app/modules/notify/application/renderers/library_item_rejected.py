"""Telegram notice that a material was rejected."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class LibraryItemRejectedRenderer(DescribedRenderer):
    """The reason and message of a rejection, with a button to the item."""

    notification_type = NotificationType.LIBRARY_ITEM_REJECTED
    link_button_key = "notify-btn-open-library-item"

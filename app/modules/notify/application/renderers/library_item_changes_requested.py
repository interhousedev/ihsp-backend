"""Telegram notice that a librarian asks for changes to a material."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class LibraryItemChangesRequestedRenderer(DescribedRenderer):
    """The librarian's message to the author, with a button to the item."""

    notification_type = NotificationType.LIBRARY_ITEM_CHANGES_REQUESTED
    link_button_key = "notify-btn-open-library-item"

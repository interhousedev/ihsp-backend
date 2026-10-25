"""Telegram notice that a material was approved and published."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class LibraryItemApprovedRenderer(DescribedRenderer):
    """The author learns that a librarian approved the material, with a button to it."""

    notification_type = NotificationType.LIBRARY_ITEM_APPROVED
    link_button_key = "notify-btn-open-library-item"

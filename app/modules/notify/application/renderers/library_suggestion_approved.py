"""Telegram notice about the decision on a book suggestion."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class LibrarySuggestionApprovedRenderer(DescribedRenderer):
    """A suggested book became a library book, with a button to it."""

    notification_type = NotificationType.LIBRARY_SUGGESTION_APPROVED
    link_button_key = "notify-btn-open-library-item"

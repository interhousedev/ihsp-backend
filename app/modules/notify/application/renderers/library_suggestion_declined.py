"""Telegram notice about the decision on a book suggestion."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class LibrarySuggestionDeclinedRenderer(DescribedRenderer):
    """A suggestion was declined, with the reason and a button to "My suggestions"."""

    notification_type = NotificationType.LIBRARY_SUGGESTION_DECLINED
    link_button_key = "notify-btn-open-library-suggestions"

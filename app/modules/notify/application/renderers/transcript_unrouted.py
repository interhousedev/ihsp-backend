"""Telegram notice: transcript unrouted."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class TranscriptUnroutedRenderer(DescribedRenderer):
    """Title, body and a button to the admission app."""

    notification_type = NotificationType.TRANSCRIPT_UNROUTED
    link_button_key = "notify-btn-open"

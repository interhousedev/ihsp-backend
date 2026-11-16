"""Telegram notice: transcript ready."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class TranscriptReadyRenderer(DescribedRenderer):
    """Title, body and a button to the admission app."""

    notification_type = NotificationType.TRANSCRIPT_READY
    link_button_key = "notify-btn-open-documents"

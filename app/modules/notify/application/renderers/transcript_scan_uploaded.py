"""Telegram notice: transcript scan uploaded."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class TranscriptScanUploadedRenderer(DescribedRenderer):
    """Title, body and a button to the admission app."""

    notification_type = NotificationType.TRANSCRIPT_SCAN_UPLOADED
    link_button_key = "notify-btn-open"

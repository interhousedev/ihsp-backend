"""Telegram notice: document rejected."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class DocumentRejectedRenderer(DescribedRenderer):
    """Title, body and a button to the admission app."""

    notification_type = NotificationType.DOCUMENT_REJECTED
    link_button_key = "notify-btn-open-documents"

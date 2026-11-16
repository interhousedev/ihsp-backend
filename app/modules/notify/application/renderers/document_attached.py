"""Telegram notice: document attached."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class DocumentAttachedRenderer(DescribedRenderer):
    """Title, body and a button to the admission app."""

    notification_type = NotificationType.DOCUMENT_ATTACHED
    link_button_key = "notify-btn-open-documents"

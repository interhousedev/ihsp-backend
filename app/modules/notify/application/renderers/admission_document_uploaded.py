"""Telegram notice: admission document uploaded."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class AdmissionDocumentUploadedRenderer(DescribedRenderer):
    """Title, body and a button to the admission app."""

    notification_type = NotificationType.ADMISSION_DOCUMENT_UPLOADED
    link_button_key = "notify-btn-open"

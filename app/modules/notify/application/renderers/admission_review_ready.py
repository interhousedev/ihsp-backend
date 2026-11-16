"""Telegram notice: admission review ready."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class AdmissionReviewReadyRenderer(DescribedRenderer):
    """Title, body and a button to the admission app."""

    notification_type = NotificationType.ADMISSION_REVIEW_READY
    link_button_key = "notify-btn-open"

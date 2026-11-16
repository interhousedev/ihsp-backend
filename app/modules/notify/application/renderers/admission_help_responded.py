"""Telegram notice: admission help responded."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class AdmissionHelpRespondedRenderer(DescribedRenderer):
    """Title, body and a button to the admission app."""

    notification_type = NotificationType.ADMISSION_HELP_RESPONDED
    link_button_key = "notify-btn-open"

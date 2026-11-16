"""Telegram notice: admission help requested."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class AdmissionHelpRequestedRenderer(DescribedRenderer):
    """Title, body and a button to the admission app."""

    notification_type = NotificationType.ADMISSION_HELP_REQUESTED
    link_button_key = "notify-btn-open"

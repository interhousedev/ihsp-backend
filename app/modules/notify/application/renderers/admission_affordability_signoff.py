"""Telegram notice: affordability sign-off request or grant."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class AdmissionAffordabilitySignoffRenderer(DescribedRenderer):
    """Title, body and a button to the admission app."""

    notification_type = NotificationType.ADMISSION_AFFORDABILITY_SIGNOFF
    link_button_key = "notify-btn-open"

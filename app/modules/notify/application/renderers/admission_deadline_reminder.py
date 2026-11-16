"""Telegram notice: admission deadline reminder."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class AdmissionDeadlineReminderRenderer(DescribedRenderer):
    """Title, body and a button to the admission app."""

    notification_type = NotificationType.ADMISSION_DEADLINE_REMINDER
    link_button_key = "notify-btn-open-deadlines"

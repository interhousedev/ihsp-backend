"""Reminder that a midterm or final control is coming."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class AssessmentReminderRenderer(DescribedRenderer):
    """Reminder 7, 3 or 1 days before a control, with a button to its prep page."""

    notification_type = NotificationType.ASSESSMENT_REMINDER
    link_button_key = "notify-btn-open-exam"

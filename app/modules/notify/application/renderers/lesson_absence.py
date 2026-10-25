"""Telegram notice to a student about an absence and its work-off task."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class LessonAbsenceRenderer(DescribedRenderer):
    """Telegram notice to a student about an absence and its work-off task."""

    notification_type = NotificationType.LESSON_ABSENCE
    link_button_key = "notify-btn-open-attendance"

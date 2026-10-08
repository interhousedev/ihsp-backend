"""Lesson change message."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class LessonChangedRenderer(DescribedRenderer):
    """Lesson change message."""

    notification_type = NotificationType.LESSON_CHANGED
    link_button_key = "notify-btn-open-lesson"

"""Telegram reminder to a teacher about temporary marks not yet in EMIS."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class TeacherTemporaryMarksRenderer(DescribedRenderer):
    """Telegram reminder to move the temporary gradebook marks to EMIS."""

    notification_type = NotificationType.TEACHER_TEMPORARY_MARKS
    link_button_key = "notify-btn-open-temporary-marks"

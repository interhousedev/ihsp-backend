"""Telegram notice to the teacher: a student submitted homework."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class HomeworkSubmittedRenderer(DescribedRenderer):
    """Title, who and which lesson, and a button to the submissions."""

    notification_type = NotificationType.HOMEWORK_SUBMITTED
    link_button_key = "notify-homework-submitted-button"

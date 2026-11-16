"""Telegram notice: admission comment added."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class AdmissionCommentAddedRenderer(DescribedRenderer):
    """Title, body and a button to the admission app."""

    notification_type = NotificationType.ADMISSION_COMMENT_ADDED
    link_button_key = "notify-btn-open"

"""Telegram notice to a curator about a low ПК or ИК mark of a student."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class CuratorExamMarkRenderer(DescribedRenderer):
    """Tells the curator a student got 2 or 3 for ПК or ИК, with a group link."""

    notification_type = NotificationType.CURATOR_EXAM_MARK
    link_button_key = "notify-btn-open-group"

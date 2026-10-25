"""Telegram digest to a curator about the absences of the group today."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class CuratorAbsencesRenderer(DescribedRenderer):
    """Telegram digest to a curator about the absences of the group today."""

    notification_type = NotificationType.CURATOR_ABSENCES
    link_button_key = "notify-btn-open-attendance"

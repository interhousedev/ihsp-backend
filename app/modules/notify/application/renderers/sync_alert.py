"""EMIS sync failure alert for Administration."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class SyncAlertRenderer(DescribedRenderer):
    """EMIS sync failure alert for Administration."""

    notification_type = NotificationType.SYNC_ALERT
    link_button_key = "notify-btn-open-monitoring"

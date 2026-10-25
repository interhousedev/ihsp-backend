"""Initial EMIS sync of a student gave up, alert for Administration."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class StudentSyncFailedRenderer(DescribedRenderer):
    """Initial EMIS sync of a student gave up, alert for Administration."""

    notification_type = NotificationType.STUDENT_SYNC_FAILED
    link_button_key = "notify-btn-open-monitoring"

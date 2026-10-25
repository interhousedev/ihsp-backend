"""New platform feedback arrived, alert for Administration."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class FeedbackNewRenderer(DescribedRenderer):
    """New platform feedback arrived, alert for Administration."""

    notification_type = NotificationType.FEEDBACK_NEW
    link_button_key = "notify-btn-open-feedback"

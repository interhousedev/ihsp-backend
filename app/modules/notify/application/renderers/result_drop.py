"""GPA or subject mark drop alert (UF-BOT-05)."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class ResultDropRenderer(DescribedRenderer):
    """GPA or subject mark drop alert (UF-BOT-05)."""

    notification_type = NotificationType.RESULT_DROP
    link_button_key = "notify-btn-open-grades"

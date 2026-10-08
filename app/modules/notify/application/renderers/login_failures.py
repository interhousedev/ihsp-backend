"""Warning about failed login attempts."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class LoginFailuresRenderer(DescribedRenderer):
    """Warning about failed login attempts."""

    notification_type = NotificationType.LOGIN_FAILURES
    link_button_key = "notify-btn-open-security"

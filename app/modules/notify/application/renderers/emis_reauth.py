"""Ask for the EMIS password again."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class EmisReauthRenderer(DescribedRenderer):
    """Ask for the EMIS password again."""

    notification_type = NotificationType.EMIS_REAUTH
    link_button_key = "notify-btn-update-emis"

"""Warning that files will be deleted."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class FilesExpiringRenderer(DescribedRenderer):
    """Warning that files will be deleted."""

    notification_type = NotificationType.FILES_EXPIRING
    link_button_key = "notify-btn-open-files"

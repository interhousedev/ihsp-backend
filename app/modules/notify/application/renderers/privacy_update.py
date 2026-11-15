"""A privacy event: export ready, erasure decided."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class PrivacyUpdateRenderer(DescribedRenderer):
    """A privacy event: export ready, erasure decided."""

    notification_type = NotificationType.PRIVACY_UPDATE
